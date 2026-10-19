import { expect, it } from "vitest";
import { receiptFromBridge, type RenderServiceRequest } from "../src/server.js";
import { mixGraph } from "../../../packages/audio-engine/tests/fixtures/piano-mix-v4.js";
import { eqGraph } from "../../../packages/audio-engine/tests/fixtures/piano-eq-v5.js";
import { buildThirtySecondSpikeGraph } from "../../../packages/audio-engine/src/spike-fixture.js";

function request(graph: import("../../../packages/audio-engine/src/contracts.js").AudioGraphSpec = mixGraph([false, false])): RenderServiceRequest {
  return { requestVersion: "render-service-request.v1", requestId: "mix",
    outputStorageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/render.wav", maximumBytes: 1_048_576,
    timeoutMs: 1000, bridgeRequest: { requestVersion: "render-bridge-request.v1", requestId: "mix",
      outputToken: "0".repeat(32), outputBitDepth: 24, graph } };
}
const receipt = { receiptVersion: "render-bridge-receipt.v1", requestId: "mix", bytes: 28844,
  durationSeconds: 0.1, sampleRate: 48000, channels: 2, bitDepth: 24, peak: 0 } as const;

it("accepts zero peak only for an exact v4 expected-silence graph", () => {
  expect(receiptFromBridge(request(), receipt, "a".repeat(64)).peak).toBe(0);
  expect(() => receiptFromBridge(request(mixGraph()), receipt, "a".repeat(64))).toThrow("RENDER_SILENT_OUTPUT");
  expect(() => receiptFromBridge(request(buildThirtySecondSpikeGraph()), receipt, "a".repeat(64))).toThrow("RENDER_SILENT_OUTPUT");
});
it("rejects zero-peak receipt with a forged v4 silence declaration and invalid peaks", () => {
  expect(() => receiptFromBridge(request({ ...mixGraph(), expectedSilence: true } as any), receipt, "a".repeat(64))).toThrow("AUDIO_GRAPH_INVALID:expectedSilence");
  for (const peak of [-1, NaN, Infinity, 1.1]) {
    expect(() => receiptFromBridge(request(), { ...receipt, peak }, "a".repeat(64))).toThrow("RENDER_PEAK_INVALID");
  }
});

it("validates v5 silence, scope and pinned EQ before accepting the page receipt", () => {
  expect(receiptFromBridge(request(eqGraph([false, false])), receipt, "a".repeat(64)).peak).toBe(0);
  expect(() => receiptFromBridge(request(eqGraph()), receipt, "a".repeat(64))).toThrow("RENDER_SILENT_OUTPUT");
  expect(() => receiptFromBridge(request(eqGraph([false, false])), { ...receipt, peak: 0.1 }, "a".repeat(64))).toThrow("RENDER_EXPECTED_SILENCE_MISMATCH");
  const malformed = structuredClone(eqGraph([false, false])) as any;
  malformed.eqProfile.mid_q = 1;
  expect(() => receiptFromBridge(request(malformed), receipt, "a".repeat(64))).toThrow("AUDIO_GRAPH_INVALID:eqProfile");
});
