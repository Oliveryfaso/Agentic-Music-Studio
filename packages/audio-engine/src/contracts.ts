import type { InstrumentPack, PianoNote } from "./instruments.js";

export const AUDIO_GRAPH_SCHEMA_VERSION = "audio-graph-spec.v1" as const;
export const AUDIO_ENGINE_VERSION = "motif-forge-audio-engine.v1" as const;

export type EqSpec = Readonly<{
  lowDb: number;
  midDb: number;
  highDb: number;
}>;

export type NoteSpec = Readonly<{
  midi: number;
  startSeconds: number;
  durationSeconds: number;
  velocity: number;
}>;

export type SampleTriggerSpec = Readonly<{
  startSeconds: number;
  gain: number;
}>;

type TrackBase = Readonly<{
  trackId: string;
  name: string;
  gainDb: number;
  pan: number;
  eq: EqSpec;
  reverbSend: number;
}>;

export type SynthTrackSpec = TrackBase &
  Readonly<{
    kind: "synth";
    presetId: BuiltinSynthPresetId;
    notes: readonly NoteSpec[];
  }>;

export type SamplerTrackSpec = TrackBase &
  Readonly<{
    kind: "sampler";
    sampleId: "builtin:click";
    sampleUrl: string;
    triggers: readonly SampleTriggerSpec[];
  }>;

export type LegacyAudioTrackSpec = SynthTrackSpec | SamplerTrackSpec;

export type AudioGraphSpecV1 = Readonly<{
  schemaVersion: typeof AUDIO_GRAPH_SCHEMA_VERSION;
  engineVersion: typeof AUDIO_ENGINE_VERSION;
  durationSeconds: number;
  sampleRate: 44100 | 48000;
  channels: 2;
  masterGainDb: number;
  reverbDecaySeconds: number;
  tracks: readonly LegacyAudioTrackSpec[];
}>;

export const AUDIO_GRAPH_SCHEMA_VERSION_V2 = "audio-graph-spec.v2" as const;
export const AUDIO_ENGINE_VERSION_V2 = "motif-forge-audio-engine.v2" as const;
export type InstrumentPackRef = Readonly<{packId:string;packVersion:string;manifestSha256:string}>;
export type PianoTrackSpec = TrackBase & Readonly<{
  kind:"multisample"; instrumentPack:InstrumentPackRef; notes:readonly PianoNote[];
}>;
export type AudioTrackSpec = LegacyAudioTrackSpec | PianoTrackSpec;
export type AudioGraphSpecV2 = Omit<AudioGraphSpecV1,"schemaVersion"|"engineVersion"|"tracks"> & Readonly<{
  schemaVersion:typeof AUDIO_GRAPH_SCHEMA_VERSION_V2;engineVersion:typeof AUDIO_ENGINE_VERSION_V2;
  tracks:readonly PianoTrackSpec[];
}>;
export const AUDIO_GRAPH_SCHEMA_VERSION_V3 = "audio-graph-spec.v3" as const;
export const AUDIO_ENGINE_VERSION_V3 = "motif-forge-audio-engine.v3" as const;
export type AudioGraphSpecV3 = Omit<AudioGraphSpecV2,"schemaVersion"|"engineVersion"> & Readonly<{
  schemaVersion:typeof AUDIO_GRAPH_SCHEMA_VERSION_V3;engineVersion:typeof AUDIO_ENGINE_VERSION_V3;
}>;
export type AudioGraphSpec = AudioGraphSpecV1 | AudioGraphSpecV2 | AudioGraphSpecV3;
/** Runtime binding supplied only by the reviewed host catalog, never stored in IR. */
export type InstrumentBinding = Readonly<{manifest:InstrumentPack;manifestSha256:string;baseUrl:string}>;

export type RenderBridgeRequest = Readonly<{
  requestVersion: "render-bridge-request.v1";
  requestId: string;
  outputToken: string;
  graph: AudioGraphSpec;
  instrumentBinding?: InstrumentBinding;
  outputBitDepth: 16 | 24;
  renderTrackIds?: readonly string[];
}>;

export type RenderBridgeReceipt = Readonly<{
  receiptVersion: "render-bridge-receipt.v1";
  requestId: string;
  bytes: number;
  durationSeconds: number;
  sampleRate: number;
  channels: number;
  bitDepth: 16 | 24;
  peak: number;
}>;

export type BuiltinSynthPresetId = "warm_pad" | "glass_pluck" | "sub_bass";

export type BuiltinSynthPreset = Readonly<{
  presetId: BuiltinSynthPresetId;
  oscillator: "sine" | "triangle" | "sawtooth";
  attack: number;
  decay: number;
  sustain: number;
  release: number;
  filterHz: number;
  filterQ: number;
  polyphony: number;
}>;
