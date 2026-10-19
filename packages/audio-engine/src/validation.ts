import { estimateRenderCapacity } from "./capacity.js";
import {
  AUDIO_ENGINE_VERSION,
  AUDIO_ENGINE_VERSION_V2,
  AUDIO_ENGINE_VERSION_V3,
  AUDIO_ENGINE_VERSION_V4,
  AUDIO_GRAPH_SCHEMA_VERSION_V4,
  AUDIO_ENGINE_VERSION_V5,
  AUDIO_GRAPH_SCHEMA_VERSION_V5,
  AUDIO_GRAPH_SCHEMA_VERSION_V3,
  AUDIO_GRAPH_SCHEMA_VERSION_V2,
  AUDIO_GRAPH_SCHEMA_VERSION,
  type AudioGraphSpec,
} from "./contracts.js";
import { BUILTIN_SYNTH_PRESETS } from "./presets.js";
import { validatePianoEqProfile, validatePianoEqSettings } from "./piano-eq.js";

function bounded(value: number, minimum: number, maximum: number, field: string): void {
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`AUDIO_GRAPH_INVALID:${field}`);
  }
}

export function validateAudioGraphSpec(spec: AudioGraphSpec): AudioGraphSpec {
  estimateRenderCapacity(spec);
  if (spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION && spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V2 && spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V3 && spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V4 && spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V5) {
    throw new Error("AUDIO_GRAPH_SCHEMA_UNSUPPORTED");
  }
  if (spec.engineVersion !== (spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V5 ? AUDIO_ENGINE_VERSION_V5 : spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V4 ? AUDIO_ENGINE_VERSION_V4 : spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V3 ? AUDIO_ENGINE_VERSION_V3 : spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V2 ? AUDIO_ENGINE_VERSION_V2 : AUDIO_ENGINE_VERSION)) {
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
  if (spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V5) {
    validatePianoEqProfile(spec.eqProfile);
    if (spec.sampleRate !== spec.eqProfile.sample_rate_hz) throw new Error("AUDIO_GRAPH_INVALID:eqProfile");
    for (const track of spec.tracks) validatePianoEqSettings(track.eq3);
  }
  if (spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V4 || spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V5) {
    if (typeof spec.expectedSilence !== "boolean") throw new Error("AUDIO_GRAPH_INVALID:expectedSilence");
    for (const track of spec.tracks) {
      if (typeof track.audible !== "boolean") throw new Error("AUDIO_GRAPH_INVALID:audible");
    }
    if (spec.expectedSilence !== !spec.tracks.some(track => track.audible))
      throw new Error("AUDIO_GRAPH_INVALID:expectedSilence");
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
    if (track.kind === "multisample") {
      if((spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V2 && spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V3 && spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V4 && spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION_V5) || spec.sampleRate !== 48000 || spec.tracks.length > (spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V2 ? 1 : 2))
        throw new Error("AUDIO_GRAPH_INVALID:pianoProfile");
      const ref=track.instrumentPack;
      if(!ref || !/^[A-Za-z0-9:._-]{1,100}$/.test(ref.packId) || !/^[A-Za-z0-9:._-]{1,100}$/.test(ref.packVersion) || !/^[a-f0-9]{64}$/.test(ref.manifestSha256))
        throw new Error("AUDIO_GRAPH_INVALID:instrumentPack");
      if(track.notes.length>2000) throw new Error("PIANO_NOTE_BUDGET_EXCEEDED");
      const noteIds=new Set<string>();
      for(const note of track.notes){
        if(!note || !/^[A-Za-z0-9:._-]{1,100}$/.test(note.noteId) || noteIds.has(note.noteId) || !Number.isInteger(note.midi) || !Number.isInteger(note.velocity))
          throw new Error("AUDIO_GRAPH_INVALID:pianoNote");
        noteIds.add(note.noteId);
        bounded(note.midi,0,127,"piano.midi");bounded(note.velocity,1,127,"piano.velocity");
        bounded(note.startSeconds,0,spec.durationSeconds,"piano.start");bounded(note.gateSeconds,.005,30,"piano.gate");
        bounded(note.detuneCents,-100,100,"piano.detune");
        if(note.startSeconds+note.gateSeconds>spec.durationSeconds+1e-6) throw new Error("AUDIO_GRAPH_INVALID:piano.range");
      }
    } else if (track.kind === "synth") {
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
    } else if (track.kind === "sampler") {
      if (track.sampleId !== "builtin:click" || !track.sampleUrl.startsWith("/assets/")) {
        throw new Error("AUDIO_GRAPH_INVALID:sample");
      }
      for (const trigger of track.triggers) {
        bounded(trigger.startSeconds, 0, spec.durationSeconds, `${track.trackId}.trigger.start`);
        bounded(trigger.gain, 0, 1, `${track.trackId}.trigger.gain`);
      }
    } else {
      throw new Error("AUDIO_GRAPH_INVALID:trackKind");
    }
    if(spec.schemaVersion !== AUDIO_GRAPH_SCHEMA_VERSION && track.kind !== "multisample")
      throw new Error("AUDIO_GRAPH_INVALID:pianoProfile");
  }
  return spec;
}


/** Scope validation is shared by the service and browser bridge. The caller's
 * silence declaration is checked, never repaired for a different selection. */
export function validateAudioRenderScope(spec: AudioGraphSpec, trackIds?: readonly string[]): readonly AudioGraphSpec["tracks"][number][] {
  validateAudioGraphSpec(spec);
  let tracks: readonly AudioGraphSpec["tracks"][number][] = spec.tracks;
  if (trackIds !== undefined) {
    const selected = new Set(trackIds);
    if (selected.size !== trackIds.length || [...selected].some(id => !spec.tracks.some(track => track.trackId === id)) ||
        ((spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V4 || spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V5) && selected.size === 0)) {
      throw new Error("AUDIO_RENDER_SCOPE_INVALID");
    }
    tracks = spec.tracks.filter(track => selected.has(track.trackId));
  }
  if ((spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V4 || spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V5) &&
      spec.expectedSilence !== !tracks.some(track => "audible" in track && track.audible === true)) {
    throw new Error("AUDIO_GRAPH_INVALID:expectedSilence");
  }
  return tracks;
}

export function validateRenderPeak(spec: AudioGraphSpec, peak: number, trackIds?: readonly string[]): void {
  validateAudioRenderScope(spec, trackIds);
  if (!Number.isFinite(peak) || peak < 0 || peak > 1) throw new Error("RENDER_PEAK_INVALID");
  const expectedSilence = (spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V4 || spec.schemaVersion === AUDIO_GRAPH_SCHEMA_VERSION_V5) && spec.expectedSilence;
  if (peak === 0 && !expectedSilence) throw new Error("RENDER_SILENT_OUTPUT");
  if (expectedSilence && peak !== 0) throw new Error("RENDER_EXPECTED_SILENCE_MISMATCH");
}
