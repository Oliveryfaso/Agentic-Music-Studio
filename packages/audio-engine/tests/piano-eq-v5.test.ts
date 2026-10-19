import { expect, it } from "vitest";
import { validateAudioGraphSpec, validateAudioRenderScope, validateRenderPeak } from "../src/validation.js";
import { eqGraph } from "./fixtures/piano-eq-v5.js";

it("accepts v5 with the pinned descriptor and per-track EQ settings", () => {
  const graph = eqGraph();
  expect(validateAudioGraphSpec(graph)).toBe(graph);
});

it.each([
  ["missingProfile", "eqProfile"], ["wrongProfile", "eqProfile"], ["wrongRate", "eqProfile"],
  ["wrongFrequency", "eqProfile"], ["wrongQ", "eqProfile"], ["wrongSlope", "eqProfile"],
  ["extraProfileField", "eqProfile"], ["missingEq", "eq3"], ["wrongEqSchema", "eq3"],
  ["wrongEqProfile", "eq3"], ["extraEqField", "eq3"], ["trackIdInEq", "eq3"],
  ["numericBypass", "eq3"], ["missingGain", "eq3"], ["stringGain", "eq3"],
  ["nanGain", "eq3"], ["infiniteGain", "eq3"], ["overGain", "eq3"], ["underGain", "eq3"],
])("rejects invalid v5 %s", (kind, field) => {
  const graph = structuredClone(eqGraph()) as any;
  const eq = graph.tracks[0].eq3;
  if (kind === "missingProfile") delete graph.eqProfile;
  if (kind === "wrongProfile") graph.eqProfile.profile_id = "unknown";
  if (kind === "wrongRate") graph.eqProfile.sample_rate_hz = 44100;
  if (kind === "wrongFrequency") graph.eqProfile.low_frequency_hz = 200;
  if (kind === "wrongQ") graph.eqProfile.mid_q = 1;
  if (kind === "wrongSlope") graph.eqProfile.shelf_slope = 0.8;
  if (kind === "extraProfileField") graph.eqProfile.extra = 1;
  if (kind === "missingEq") delete graph.tracks[0].eq3;
  if (kind === "wrongEqSchema") eq.schema_version = "piano-eq.v2";
  if (kind === "wrongEqProfile") eq.profile_id = "unknown";
  if (kind === "extraEqField") eq.enabled = true;
  if (kind === "trackIdInEq") eq.track_id = graph.tracks[0].trackId;
  if (kind === "numericBypass") eq.bypass = 1;
  if (kind === "missingGain") delete eq.mid_gain_db;
  if (kind === "stringGain") eq.mid_gain_db = "6";
  if (kind === "nanGain") eq.mid_gain_db = NaN;
  if (kind === "infiniteGain") eq.mid_gain_db = Infinity;
  if (kind === "overGain") eq.mid_gain_db = 12.01;
  if (kind === "underGain") eq.mid_gain_db = -12.01;
  expect(() => validateAudioGraphSpec(graph)).toThrow(`AUDIO_GRAPH_INVALID:${field}`);
});

it("carries v4 scope and silence checks into v5 without allowing forged silence", () => {
  const silent = eqGraph([false, false]);
  expect(() => validateRenderPeak(silent, 0)).not.toThrow();
  expect(() => validateRenderPeak(silent, 0.1)).toThrow("RENDER_EXPECTED_SILENCE_MISMATCH");
  expect(() => validateRenderPeak(eqGraph(), 0)).toThrow("RENDER_SILENT_OUTPUT");
  expect(() => validateAudioRenderScope(eqGraph(), ["piano-1"])).toThrow("AUDIO_GRAPH_INVALID:expectedSilence");
  expect(() => validateAudioRenderScope(eqGraph(), [])).toThrow("AUDIO_RENDER_SCOPE_INVALID");
  expect(() => validateAudioGraphSpec({ ...eqGraph(), expectedSilence: true } as any)).toThrow("AUDIO_GRAPH_INVALID:expectedSilence");
});

it("rejects a graph/engine version mismatch before rendering", () => {
  expect(() => validateAudioGraphSpec({ ...eqGraph(), engineVersion: "motif-forge-audio-engine.v4" } as any))
    .toThrow("AUDIO_ENGINE_VERSION_UNSUPPORTED");
});
