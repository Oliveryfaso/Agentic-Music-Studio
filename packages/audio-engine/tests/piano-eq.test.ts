import { expect, it } from "vitest";
import { connectPianoEq, eqResponseDb, PIANO_EQ_PROFILE, type PianoEqSettings } from "../src/piano-eq.js";
import { flatEq, eqProfile } from "./fixtures/piano-eq-v5.js";

it("pins the same serialized profile consumed by the backend graph", () => {
  expect(PIANO_EQ_PROFILE).toEqual(eqProfile);
  expect(Object.isFrozen(PIANO_EQ_PROFILE)).toBe(true);
});

it("has exact flat response for zero gains and bypass without changing saved gains", () => {
  const bypass = { ...flatEq, bypass: true, low_gain_db: 12, mid_gain_db: -6, high_gain_db: 6 };
  for (const frequency of [0, 20, 180, 1000, 6000, 20000, 24000]) {
    expect(eqResponseDb(flatEq, eqProfile, frequency)).toBe(0);
    expect(eqResponseDb(bypass, eqProfile, frequency)).toBe(0);
  }
  expect(bypass).toMatchObject({ low_gain_db: 12, mid_gain_db: -6, high_gain_db: 6 });
});

it.each([-12, -6, 6, 12])("has the requested %s dB peak and shelf endpoints", (gain) => {
  expect(eqResponseDb({ ...flatEq, mid_gain_db: gain }, eqProfile, 1000)).toBeCloseTo(gain, 8);
  expect(eqResponseDb({ ...flatEq, low_gain_db: gain }, eqProfile, 0)).toBeCloseTo(gain, 8);
  expect(eqResponseDb({ ...flatEq, low_gain_db: gain }, eqProfile, 24000)).toBeCloseTo(0, 8);
  expect(eqResponseDb({ ...flatEq, high_gain_db: gain }, eqProfile, 0)).toBeCloseTo(0, 8);
  expect(eqResponseDb({ ...flatEq, high_gain_db: gain }, eqProfile, 24000)).toBeCloseTo(gain, 8);
  expect(eqResponseDb({ ...flatEq, low_gain_db: gain }, eqProfile, 180)).toBeCloseTo(gain / 2, 8);
  expect(eqResponseDb({ ...flatEq, high_gain_db: gain }, eqProfile, 6000)).toBeCloseTo(gain / 2, 8);
});

it("cascades the three responses and makes equal boost/cut reciprocal", () => {
  const eq = { ...flatEq, low_gain_db: 6, mid_gain_db: -3, high_gain_db: 9 };
  for (const frequency of [20, 100, 180, 400, 1000, 3000, 6000, 12000, 20000]) {
    const singles = [
      { ...flatEq, low_gain_db: eq.low_gain_db }, { ...flatEq, mid_gain_db: eq.mid_gain_db },
      { ...flatEq, high_gain_db: eq.high_gain_db },
    ].reduce((sum, band) => sum + eqResponseDb(band, eqProfile, frequency), 0);
    expect(eqResponseDb(eq, eqProfile, frequency)).toBeCloseTo(singles, 10);
    const inverse = { ...eq, low_gain_db: -6, mid_gain_db: 3, high_gain_db: -9 };
    expect(eqResponseDb(eq, eqProfile, frequency) + eqResponseDb(inverse, eqProfile, frequency)).toBeCloseTo(0, 8);
  }
});

it.each([-1, NaN, Infinity, 24001])("rejects invalid curve frequency %s", frequency => {
  expect(() => eqResponseDb(flatEq, eqProfile, frequency)).toThrow("PIANO_EQ_FREQUENCY_INVALID");
});

class NativeNode {
  connections: NativeNode[] = [];
  type = ""; frequency = { value: 350 }; gain = { value: 0 }; Q = { value: 1 };
  connect(node: NativeNode) { this.connections.push(node); return node; }
}
function nativeGraph(sampleRate = 48000) {
  const filters: NativeNode[] = [];
  const context = { sampleRate, createBiquadFilter() { const node = new NativeNode(); filters.push(node); return node; } };
  const input = new NativeNode(), output = new NativeNode();
  const connect = (eq: PianoEqSettings) => connectPianoEq(context as unknown as BaseAudioContext,
    input as unknown as AudioNode, output as unknown as AudioNode, eq, eqProfile);
  return { context, filters, input, output, connect };
}

it.each([{ ...flatEq }, { ...flatEq, bypass: true, low_gain_db: 6 }])("connects directly without new filters for $bypass bypass / zero gains", eq => {
  const graph = nativeGraph();
  expect(graph.connect(eq)).toEqual([]);
  expect(graph.filters).toEqual([]);
  expect(graph.input.connections).toEqual([graph.output]);
});

it("connects at most three native filters in low/mid/high order using the shared profile", () => {
  const graph = nativeGraph();
  expect(graph.connect({ ...flatEq, low_gain_db: 6, mid_gain_db: -3, high_gain_db: 12 })).toEqual(graph.filters);
  expect(graph.filters.map(node => [node.type, node.frequency.value, node.gain.value])).toEqual([
    ["lowshelf", 180, 6], ["peaking", 1000, -3], ["highshelf", 6000, 12],
  ]);
  expect(graph.filters[1]!.Q.value).toBe(0.8);
  expect(graph.input.connections).toEqual([graph.filters[0]]);
  expect(graph.filters.map(node => node.connections)).toEqual([[graph.filters[1]], [graph.filters[2]], [graph.output]]);
});

it("skips an individual zero-gain band", () => {
  const graph = nativeGraph();
  graph.connect({ ...flatEq, low_gain_db: 6, high_gain_db: -6 });
  expect(graph.filters.map(node => node.type)).toEqual(["lowshelf", "highshelf"]);
});

it("rejects a context that disagrees with the pinned sample rate before connecting", () => {
  const graph = nativeGraph(44100);
  expect(() => graph.connect(flatEq)).toThrow("AUDIO_GRAPH_INVALID:eqProfile");
  expect(graph.input.connections).toEqual([]);
});
