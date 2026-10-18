import { describe, expect, it, vi } from "vitest";
import { buildThirtySecondSpikeGraph } from "../../../packages/audio-engine/src/spike-fixture.js";

const mocks = vi.hoisted(() => ({ launch: vi.fn() }));
vi.mock("playwright", () => ({ chromium: { launch: mocks.launch } }));
import { ChromiumRenderExecutor } from "../src/executor.js";

describe("executor cancellation", () => {
  it("does not begin a render when cancellation arrives during page recreation", async () => {
    let finishNavigation: () => void = () => undefined;
    const navigating = new Promise<void>(resolve => { finishNavigation = resolve; });
    const evaluate = vi.fn(async () => { throw new Error("UNEXPECTED_RENDER_STARTED"); });
    const firstPage={goto:vi.fn(async()=>undefined),isClosed:()=>true};
    const secondPage={goto:vi.fn(()=>navigating),isClosed:()=>false,evaluate,close:vi.fn(async()=>undefined)};
    mocks.launch.mockResolvedValue({newPage:vi.fn().mockResolvedValueOnce(firstPage).mockResolvedValueOnce(secondPage),close:vi.fn(async()=>undefined)});
    const executor=new ChromiumRenderExecutor("/unused-test-root");
    await executor.start();
    try {
      const cancel=new AbortController();
      const result=executor.render({requestVersion:"render-service-request.v1",requestId:"cancel-during-goto",
        outputStorageKey:"jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/render.wav",maximumBytes:8_640_044,timeoutMs:1000,
        bridgeRequest:{requestVersion:"render-bridge-request.v1",requestId:"cancel-during-goto",
          outputToken:"0".repeat(32),outputBitDepth:24,graph:buildThirtySecondSpikeGraph()}},cancel.signal);
      await vi.waitFor(()=>expect(secondPage.goto).toHaveBeenCalled());
      cancel.abort();finishNavigation();
      await expect(result).rejects.toThrow("RENDER_CLIENT_DISCONNECTED");
      expect(evaluate).not.toHaveBeenCalled();
    } finally {finishNavigation();await executor.close();}
  });
});
