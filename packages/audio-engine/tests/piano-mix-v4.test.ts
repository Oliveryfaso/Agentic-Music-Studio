import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { validateAudioGraphSpec } from "../src/validation.js";
import { renderAudioGraphOffline } from "../src/compiler.js";
import { encodeStereoPcm24 } from "../src/wav.js";
import { mixGraph } from "./fixtures/piano-mix-v4.js";
import type { AudioGraphSpec } from "../src/contracts.js";

const calls = vi.hoisted(() => ({ prepare: vi.fn(), plan: vi.fn(), schedule: vi.fn(), offline: vi.fn() }));
vi.mock("../src/piano-runtime.js", () => ({ preparePiano: calls.prepare }));
vi.mock("../src/instruments.js", () => ({ planPianoVoices: calls.plan, schedulePianoVoices: calls.schedule }));
vi.mock("tone", () => {
  class Node { input = {}; connect() { return this; } toDestination() { return this; } }
  return { Offline: calls.offline, Limiter: Node, Gain: Node, Convolver: Node, EQ3: Node, Panner: Node,
    getContext: () => ({ rawContext: {} }) };
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
  vi.clearAllMocks(); vi.stubGlobal("AudioBuffer", ZeroBuffer);
  calls.prepare.mockResolvedValue({ pack: {}, voices: [], buffers: new Map() });
  calls.offline.mockImplementation(async (render: () => Promise<void>) => {
    await render(); return { get: () => new ZeroBuffer({ numberOfChannels: 2, sampleRate: 48000, length: 4800 }) };
  });
});
afterEach(() => vi.unstubAllGlobals());

it("accepts version 4 with explicit per-track audibility and exact silence declaration", () => {
  for (const flags of [[true, false], [false, true], [false, false]]) {
    const graph = mixGraph(flags); expect(validateAudioGraphSpec(graph)).toBe(graph);
  }
});

it.each(["missingAudible", "numericAudible", "missingSilence", "numericSilence", "falseSilence", "thirdPiano", "wrongEngine"])(
  "rejects malformed v4 mix: %s", (kind) => {
    const graph = structuredClone(mixGraph()) as any;
    if (kind === "missingAudible") delete graph.tracks[0].audible;
    if (kind === "numericAudible") graph.tracks[0].audible = 1;
    if (kind === "missingSilence") delete graph.expectedSilence;
    if (kind === "numericSilence") graph.expectedSilence = 0;
    if (kind === "falseSilence") graph.expectedSilence = true;
    if (kind === "thirdPiano") graph.tracks.push({ ...graph.tracks[0], trackId: "third" });
    if (kind === "wrongEngine") graph.engineVersion = "motif-forge-audio-engine.v3";
    const expected = kind === "wrongEngine" ? "AUDIO_ENGINE_VERSION_UNSUPPORTED"
      : kind === "thirdPiano" ? "AUDIO_GRAPH_INVALID:pianoProfile"
      : kind.endsWith("Audible") ? "AUDIO_GRAPH_INVALID:audible" : "AUDIO_GRAPH_INVALID:expectedSilence";
    expect(() => validateAudioGraphSpec(graph)).toThrow(expected);
  },
);

it("does not prepare or schedule inaudible tracks", async () => {
  await renderAudioGraphOffline(mixGraph());
  expect(calls.prepare).toHaveBeenCalledTimes(1);
  expect(calls.prepare.mock.calls[0]![0].trackId).toBe("piano-0");
  expect(calls.schedule).toHaveBeenCalledTimes(1);
});

it("all-muted v4 encodes exact zero PCM without loading samples or starting Tone", async () => {
  const buffer = await renderAudioGraphOffline(mixGraph([false, false]));
  expect(buffer.length).toBe(4800);
  expect([...encodeStereoPcm24(buffer).subarray(44)].every(value => value === 0)).toBe(true);
  expect(calls.prepare).not.toHaveBeenCalled(); expect(calls.schedule).not.toHaveBeenCalled();
  expect(calls.offline).not.toHaveBeenCalled();
});

it("rejects a selection that contradicts expectedSilence rather than rewriting it", async () => {
  await expect(renderAudioGraphOffline(mixGraph(), ["piano-1"])).rejects.toThrow("AUDIO_GRAPH_INVALID:expectedSilence");
  await expect(renderAudioGraphOffline(mixGraph(), [])).rejects.toThrow("AUDIO_RENDER_SCOPE_INVALID");
});

it("keeps legacy v3 scheduling unchanged when an unversioned audible field appears", async () => {
  const v4 = mixGraph([false, false]);
  const legacy = { ...v4, schemaVersion: "audio-graph-spec.v3", engineVersion: "motif-forge-audio-engine.v3" } as unknown as AudioGraphSpec;
  await renderAudioGraphOffline(legacy);
  expect(calls.prepare).toHaveBeenCalledTimes(2); expect(calls.schedule).toHaveBeenCalledTimes(2);
});


it.each([{ scope: ["unknown"] }, { scope: ["piano-0", "piano-0"] }])("rejects invalid scope $scope before sample loading", async ({ scope }) => {
  await expect(renderAudioGraphOffline(mixGraph(), scope)).rejects.toThrow("AUDIO_RENDER_SCOPE_INVALID");
  expect(calls.prepare).not.toHaveBeenCalled();
});
