import {
  AUDIO_ENGINE_VERSION,
  AUDIO_GRAPH_SCHEMA_VERSION,
  type AudioGraphSpec,
} from "./contracts.js";
import { BUILTIN_SYNTH_PRESETS } from "./presets.js";

function bounded(value: number, minimum: number, maximum: number, field: string): void {
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`AUDIO_GRAPH_INVALID:${field}`);
  }
}

export function validateAudioGraphSpec(spec: AudioGraphSpec): AudioGraphSpec {
  if (spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION) {
    throw new Error("AUDIO_GRAPH_SCHEMA_UNSUPPORTED");
  }
  if (spec.engineVersion !== AUDIO_ENGINE_VERSION) {
    throw new Error("AUDIO_ENGINE_VERSION_UNSUPPORTED");
  }
  bounded(spec.durationSeconds, 0.1, 300, "durationSeconds");
  if (spec.sampleRate !== 44100 && spec.sampleRate !== 48000) {
    throw new Error("AUDIO_GRAPH_INVALID:sampleRate");
  }
  if (spec.channels !== 2) {
    throw new Error("AUDIO_GRAPH_INVALID:channels");
  }
  bounded(spec.masterGainDb, -36, 0, "masterGainDb");
  bounded(spec.reverbDecaySeconds, 0.1, 8, "reverbDecaySeconds");
  if (spec.tracks.length < 1 || spec.tracks.length > 12) {
    throw new Error("AUDIO_GRAPH_INVALID:tracks");
  }
  const ids = new Set<string>();
  for (const track of spec.tracks) {
    if (!track.trackId || ids.has(track.trackId)) {
      throw new Error("AUDIO_GRAPH_INVALID:trackId");
    }
    ids.add(track.trackId);
    bounded(track.gainDb, -60, 6, `${track.trackId}.gainDb`);
    bounded(track.pan, -1, 1, `${track.trackId}.pan`);
    bounded(track.reverbSend, 0, 1, `${track.trackId}.reverbSend`);
    bounded(track.eq.lowDb, -12, 12, `${track.trackId}.eq.lowDb`);
    bounded(track.eq.midDb, -12, 12, `${track.trackId}.eq.midDb`);
    bounded(track.eq.highDb, -12, 12, `${track.trackId}.eq.highDb`);
    if (track.kind === "synth") {
      if (!(track.presetId in BUILTIN_SYNTH_PRESETS)) {
        throw new Error("AUDIO_GRAPH_INVALID:presetId");
      }
      for (const note of track.notes) {
        bounded(note.midi, 0, 127, `${track.trackId}.note.midi`);
        bounded(note.velocity, 0, 1, `${track.trackId}.note.velocity`);
        bounded(note.startSeconds, 0, spec.durationSeconds, `${track.trackId}.note.start`);
        bounded(note.durationSeconds, 0.01, 30, `${track.trackId}.note.duration`);
        if (note.startSeconds + note.durationSeconds > spec.durationSeconds + 0.001) {
          throw new Error(`AUDIO_GRAPH_INVALID:${track.trackId}.note.range`);
        }
      }
    } else {
      if (track.sampleId !== "builtin:click" || !track.sampleUrl.startsWith("/assets/")) {
        throw new Error("AUDIO_GRAPH_INVALID:sample");
      }
      for (const trigger of track.triggers) {
        bounded(trigger.startSeconds, 0, spec.durationSeconds, `${track.trackId}.trigger.start`);
        bounded(trigger.gain, 0, 1, `${track.trackId}.trigger.gain`);
      }
    }
  }
  return spec;
}
