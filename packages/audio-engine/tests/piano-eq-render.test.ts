import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderAudioGraphOffline } from "../src/compiler.js";
import { eqGraph } from "./fixtures/piano-eq-v5.js";
import { mixGraph } from "./fixtures/piano-mix-v4.js";
import { encodeStereoPcm24 } from "../src/wav.js";

const calls = vi.hoisted(() => ({ prepare: vi.fn(), plan: vi.fn(), schedule: vi.fn(), offline: vi.fn(),
  eq: vi.fn(), native: vi.fn(), edges: [] as string[][] }));
vi.mock("../src/piano-runtime.js", () => ({ preparePiano: calls.prepare }));
vi.mock("../src/instruments.js", () => ({ planPianoVoices: calls.plan, schedulePianoVoices: calls.schedule }));
vi.mock("tone", () => {
  class Native {
    type = ""; frequency = { value: 0 }; gain = { value: 0 }; Q = { value: 1 };
    constructor(readonly name: string) {}
    connect(node: Native) { calls.edges.push([this.type || this.name, node.type || node.name]); return node; }
  }
  class Node {
    input = new Native("panner"); output = { output: new Native("eq3") };
    connect() { return this; } toDestination() { return this; }
  }
  class EQ3 extends Node {
    constructor(...gains: number[]) { super(); calls.eq(...gains); }
  }
  return { Offline: calls.offline, Limiter: Node, Gain: Node, Convolver: Node, EQ3, Panner: Node,
    getContext: () => ({ rawContext: { sampleRate: 48000, createBiquadFilter: () => {
      const node = new Native("filter"); calls.native(node); return node;
    } } }) };
});

class ZeroBuffer {
  numberOfChannels: number; sampleRate: number; length: number; duration: number;
  private readonly data: Float32Array[];
  constructor(options: { numberOfChannels: number; sampleRate: number; length: number }) {
    this.numberOfChannels = options.numberOfChannels; this.sampleRate = options.sampleRate;
    this.length = options.length; this.duration = this.length / this.sampleRate;
    this.data = Array.from({ length: this.numberOfChannels }, () => new Float32Array(this.length));
  }
  getChannelData(index: number) { return this.data[index]!; }
}
beforeEach(() => {
  vi.clearAllMocks(); calls.edges.length = 0; vi.stubGlobal("AudioBuffer", ZeroBuffer);
  calls.prepare.mockResolvedValue({ pack: {}, voices: [], buffers: new Map() });
  calls.offline.mockImplementation(async (render: () => Promise<void>) => {
    await render(); return { get: () => new ZeroBuffer({ numberOfChannels: 2, sampleRate: 48000, length: 4800 }) };
  });
});
afterEach(() => vi.unstubAllGlobals());

it("keeps the historical EQ3 and inserts three native bands before the existing panner", async () => {
  const graph = structuredClone(eqGraph()) as any;
  graph.tracks[0].eq = { lowDb: -1, midDb: 2, highDb: -3 };
  graph.tracks[0].eq3 = { ...graph.tracks[0].eq3, low_gain_db: 6, mid_gain_db: -3, high_gain_db: 9 };
  await renderAudioGraphOffline(graph);
  expect(calls.eq).toHaveBeenCalledExactlyOnceWith(-1, 2, -3);
  expect(calls.native).toHaveBeenCalledTimes(3);
  expect(calls.edges).toEqual([["eq3", "lowshelf"], ["lowshelf", "peaking"], ["peaking", "highshelf"], ["highshelf", "panner"]]);
  expect(calls.prepare).toHaveBeenCalledTimes(1); expect(calls.schedule).toHaveBeenCalledTimes(1);
});

it.each([false, true])("adds no native filters for v5 flat/bypass=%s", async bypass => {
  const graph = structuredClone(eqGraph()) as any;
  graph.tracks[0].eq3.bypass = bypass;
  graph.tracks[0].eq3.low_gain_db = bypass ? 6 : 0;
  await renderAudioGraphOffline(graph);
  expect(calls.native).not.toHaveBeenCalled();
  expect(calls.edges).toEqual([["eq3", "panner"]]);
  expect(calls.eq).toHaveBeenCalledTimes(1);
});

it("does not reinterpret legacy v4 when an unversioned EQ field appears", async () => {
  const graph = structuredClone(mixGraph()) as any;
  graph.eqProfile = (eqGraph() as any).eqProfile;
  graph.tracks[0].eq3 = { ...(eqGraph() as any).tracks[0].eq3, low_gain_db: 12 };
  await renderAudioGraphOffline(graph);
  expect(calls.eq).toHaveBeenCalledTimes(1); expect(calls.native).not.toHaveBeenCalled();
  expect(calls.edges).toEqual([]);
});

it("all-muted v5 produces exact zero PCM without sample work or Tone", async () => {
  const buffer = await renderAudioGraphOffline(eqGraph([false, false]));
  expect([...encodeStereoPcm24(buffer).subarray(44)].every(value => value === 0)).toBe(true);
  expect(calls.prepare).not.toHaveBeenCalled(); expect(calls.schedule).not.toHaveBeenCalled();
  expect(calls.native).not.toHaveBeenCalled(); expect(calls.offline).not.toHaveBeenCalled();
});
