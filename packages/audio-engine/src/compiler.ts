import * as Tone from "tone";

import type { AudioGraphSpec, InstrumentBinding } from "./contracts.js";
import { preparePiano, type PreparedPiano } from "./piano-runtime.js";
import { planPianoVoices, schedulePianoVoices } from "./instruments.js";
import { BUILTIN_SYNTH_PRESETS } from "./presets.js";
import { validateAudioGraphSpec, validateAudioRenderScope } from "./validation.js";

function dbToGain(db: number): number {
  return 10 ** (db / 20);
}

function deterministicReverbImpulse(durationSeconds: number, sampleRate: number): AudioBuffer {
  const length = Math.max(1, Math.round(durationSeconds * sampleRate));
  const impulse = new AudioBuffer({ length, numberOfChannels: 2, sampleRate });
  let seed = 0x4d4f5449;
  for (let channel = 0; channel < impulse.numberOfChannels; channel += 1) {
    const data = impulse.getChannelData(channel);
    for (let index = 0; index < length; index += 1) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const noise = (seed / 0x1_0000_0000) * 2 - 1;
      const envelope = (1 - index / length) ** 2.4;
      data[index] = noise * envelope * 0.32;
    }
  }
  return impulse;
}

export async function renderAudioGraphOffline(
  uncheckedSpec: AudioGraphSpec,
  trackIds?: readonly string[],
  instrumentBinding?: InstrumentBinding,
): Promise<AudioBuffer> {
  const spec = validateAudioGraphSpec(uncheckedSpec);
  const selected = validateAudioRenderScope(spec, trackIds);
  const tracks = spec.schemaVersion === "audio-graph-spec.v4"
    ? selected.filter(track => "audible" in track && track.audible === true)
    : selected;
  if (spec.schemaVersion === "audio-graph-spec.v4" && spec.expectedSilence) {
    // Native AudioBuffer storage starts at exact digital zero. No pack decode,
    // voice scheduling, convolution or Tone graph is needed for an all-muted mix.
    return new AudioBuffer({ length: Math.ceil(spec.durationSeconds * spec.sampleRate),
      numberOfChannels: spec.channels, sampleRate: spec.sampleRate });
  }
  const reverbImpulse = deterministicReverbImpulse(
    spec.reverbDecaySeconds,
    spec.sampleRate,
  );
  const pianoTracks=tracks.filter(track=>track.kind === "multisample");
  if(pianoTracks.length && instrumentBinding){
    // The pack's polyphony budget applies to the complete performance, across parts.
    planPianoVoices(instrumentBinding.manifest,pianoTracks.flatMap(track=>track.notes),spec.durationSeconds);
  }
  const renderBuffers=new Map<string,AudioBuffer>();
  const pianos = new Map<string,PreparedPiano>();
  const sampleBuffers = new Map<string, Tone.ToneAudioBuffer>();
  for (const track of tracks) {
    if(track.kind === "multisample") pianos.set(track.trackId,await preparePiano(track,instrumentBinding,spec.durationSeconds,spec.sampleRate,renderBuffers));
    if (track.kind === "sampler" && !sampleBuffers.has(track.sampleUrl)) {
      sampleBuffers.set(track.sampleUrl, await Tone.ToneAudioBuffer.fromUrl(track.sampleUrl));
    }
  }

  const rendered = await Tone.Offline(
    async () => {
      const limiter = new Tone.Limiter(-1).toDestination();
      const master = new Tone.Gain(dbToGain(spec.masterGainDb)).connect(limiter);
      const reverb = new Tone.Convolver(reverbImpulse).connect(master);

      for (const track of tracks) {
        const eq = new Tone.EQ3(track.eq.lowDb, track.eq.midDb, track.eq.highDb);
        const panner = new Tone.Panner(track.pan);
        const trackGain = new Tone.Gain(dbToGain(track.gainDb));
        const send = new Tone.Gain(track.reverbSend).connect(reverb);
        eq.connect(panner);
        panner.connect(trackGain);
        trackGain.connect(master);
        trackGain.connect(send);

        if (track.kind === "synth") {
          const preset = BUILTIN_SYNTH_PRESETS[track.presetId];
          const synth = new Tone.PolySynth(Tone.Synth, {
            oscillator: { type: preset.oscillator },
            envelope: {
              attack: preset.attack,
              decay: preset.decay,
              sustain: preset.sustain,
              release: preset.release,
            },
          });
          synth.maxPolyphony = preset.polyphony;
          const filter = new Tone.Filter(preset.filterHz, "lowpass", -12);
          filter.Q.value = preset.filterQ;
          synth.connect(filter);
          filter.connect(eq);
          for (const note of track.notes) {
            synth.triggerAttackRelease(
              Tone.Frequency(note.midi, "midi").toFrequency(),
              note.durationSeconds,
              note.startSeconds,
              note.velocity,
            );
          }
        } else if(track.kind === "multisample") {
          const piano=pianos.get(track.trackId);
          if(!piano) throw new Error("INSTRUMENT_PACK_UNAVAILABLE");
          const input=new Tone.Gain(1).connect(eq);
          schedulePianoVoices(Tone.getContext().rawContext as unknown as BaseAudioContext,
            input.input as unknown as AudioNode,piano.pack,piano.voices,piano.buffers);
        } else {
          const sample = sampleBuffers.get(track.sampleUrl);
          if (sample === undefined) {
            throw new Error("AUDIO_SAMPLE_BUFFER_MISSING");
          }
          for (const trigger of track.triggers) {
            const player = new Tone.Player(sample).connect(eq);
            player.fadeOut = 0.01;
            player.volume.setValueAtTime(Tone.gainToDb(Math.max(trigger.gain, 0.0001)), trigger.startSeconds);
            player.start(trigger.startSeconds);
          }
        }
      }
    },
    spec.durationSeconds,
    spec.channels,
    spec.sampleRate,
  );
  const audioBuffer = rendered.get();
  if (audioBuffer === undefined) {
    throw new Error("AUDIO_OFFLINE_BUFFER_MISSING");
  }
  return audioBuffer;
}
