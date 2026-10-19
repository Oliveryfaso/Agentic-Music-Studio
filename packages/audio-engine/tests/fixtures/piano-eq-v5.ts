import type { AudioGraphSpecV5 } from "../../src/contracts.js";
import { mixGraph } from "./piano-mix-v4.js";

export const eqProfile = {
  schema_version: "three-band-eq-profile.v1", profile_id: "motif-three-band-static.v1",
  sample_rate_hz: 48000, low_frequency_hz: 180, mid_frequency_hz: 1000,
  mid_q: 0.8, high_frequency_hz: 6000, shelf_slope: 1,
} as const;
export const flatEq = {
  schema_version: "piano-eq.v1", profile_id: "motif-three-band-static.v1",
  bypass: false, low_gain_db: 0, mid_gain_db: 0, high_gain_db: 0,
} as const;

export function eqGraph(audible = [true, false]): AudioGraphSpecV5 {
  const mix = mixGraph(audible);
  return { ...mix, schemaVersion: "audio-graph-spec.v5", engineVersion: "motif-forge-audio-engine.v5",
    eqProfile, tracks: mix.tracks.map(track => ({ ...track, eq3: { ...flatEq } })),
  };
}
