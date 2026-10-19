import { beforeEach, expect, it, vi } from "vitest";
import { eqGraph } from "../../../packages/audio-engine/tests/fixtures/piano-eq-v5.js";
import type { RenderServiceRequest } from "../src/server.js";

const mocks = vi.hoisted(() => ({ launch: vi.fn(), evaluate: vi.fn() }));
vi.mock("playwright", () => ({ chromium: { launch: mocks.launch } }));
// Catalog dispatch needs no socket, browser process or WAV output.
vi.mock("../src/runtime.js", () => ({
  createBuiltinClickWav: () => new Uint8Array(), withTimeout: (value: Promise<unknown>) => value,
  LoopbackRenderServer: class {
    origin = "http://unit-test";
    registerInstrumentPack() {} registerSink() {} async cancelSink() {} async start() {} async close() {}
  },
}));
import { ChromiumRenderExecutor } from "../src/executor.js";

beforeEach(() => {
  vi.clearAllMocks();
  mocks.evaluate.mockRejectedValue(new Error("STOP_AFTER_BINDING"));
  const page = { goto: async () => undefined, isClosed: () => false, evaluate: mocks.evaluate };
  mocks.launch.mockResolvedValue({ newPage: async () => page, close: async () => undefined });
});
const request = (): RenderServiceRequest => ({
  requestVersion: "render-service-request.v1", requestId: "eq-catalog",
  outputStorageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/render.wav", maximumBytes: 1_048_576,
  timeoutMs: 1000, bridgeRequest: { requestVersion: "render-bridge-request.v1", requestId: "eq-catalog",
    outputToken: "0".repeat(32), outputBitDepth: 24, graph: eqGraph() },
});
const catalog = (pin = "a".repeat(64)) => ({ manifest: {
  packId: "freepats:upright-kw-small", packVersion: "2019-07-03.motif1",
}, manifestSha256: pin, sample: () => undefined }) as any;

it.each(["missing", "wrong-pin"])("refuses v5 %s catalog before browser evaluation", async mode => {
  const executor = new ChromiumRenderExecutor("/unused-test-root", mode === "missing" ? undefined : catalog("b".repeat(64)));
  await executor.start();
  try {
    await expect(executor.render(request())).rejects.toThrow(mode === "missing" ? "INSTRUMENT_PACK_UNAVAILABLE" : "INSTRUMENT_MANIFEST_HASH_MISMATCH");
    expect(mocks.evaluate).not.toHaveBeenCalled();
  } finally { await executor.close(); }
});

it("binds the reviewed v5 catalog and preserves graph profile/settings for the shared page", async () => {
  const reviewed = catalog();
  const executor = new ChromiumRenderExecutor("/unused-test-root", reviewed);
  await executor.start();
  try {
    await expect(executor.render(request())).rejects.toThrow("STOP_AFTER_BINDING");
    const bridge = mocks.evaluate.mock.calls[0]![1];
    expect(bridge.graph).toEqual(request().bridgeRequest.graph);
    expect(bridge.instrumentBinding).toMatchObject({ manifest: reviewed.manifest, manifestSha256: "a".repeat(64) });
    expect(bridge.instrumentBinding.baseUrl).toMatch(/^\/instrument-packs\/[a-f0-9]{32}$/);
  } finally { await executor.close(); }
});
