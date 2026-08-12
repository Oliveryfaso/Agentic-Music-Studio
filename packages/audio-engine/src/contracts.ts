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

export type AudioTrackSpec = SynthTrackSpec | SamplerTrackSpec;

export type AudioGraphSpec = Readonly<{
  schemaVersion: typeof AUDIO_GRAPH_SCHEMA_VERSION;
  engineVersion: typeof AUDIO_ENGINE_VERSION;
  durationSeconds: number;
  sampleRate: 44100 | 48000;
  channels: 2;
  masterGainDb: number;
  reverbDecaySeconds: number;
  tracks: readonly AudioTrackSpec[];
}>;

export type RenderBridgeRequest = Readonly<{
  requestVersion: "render-bridge-request.v1";
  requestId: string;
  outputToken: string;
  graph: AudioGraphSpec;
  renderTrackIds?: readonly string[];
}>;

export type RenderBridgeReceipt = Readonly<{
  receiptVersion: "render-bridge-receipt.v1";
  requestId: string;
  bytes: number;
  durationSeconds: number;
  sampleRate: number;
  channels: number;
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
