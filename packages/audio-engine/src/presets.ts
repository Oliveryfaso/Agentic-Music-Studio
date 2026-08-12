import type { BuiltinSynthPreset, BuiltinSynthPresetId } from "./contracts.js";

export const BUILTIN_SYNTH_PRESETS: Readonly<Record<BuiltinSynthPresetId, BuiltinSynthPreset>> = {
  warm_pad: {
    presetId: "warm_pad",
    oscillator: "triangle",
    attack: 0.45,
    decay: 0.8,
    sustain: 0.72,
    release: 1.8,
    filterHz: 2400,
    filterQ: 0.7,
    polyphony: 8,
  },
  glass_pluck: {
    presetId: "glass_pluck",
    oscillator: "sine",
    attack: 0.005,
    decay: 0.35,
    sustain: 0.08,
    release: 0.7,
    filterHz: 5600,
    filterQ: 1.2,
    polyphony: 8,
  },
  sub_bass: {
    presetId: "sub_bass",
    oscillator: "sine",
    attack: 0.02,
    decay: 0.18,
    sustain: 0.82,
    release: 0.28,
    filterHz: 420,
    filterQ: 0.8,
    polyphony: 4,
  },
};
