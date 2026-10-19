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

it.each(['missing','wrong-pin'] as const)('refuses piano %s before evaluation with no legacy fallback',async(mode)=>{
  const evaluate=vi.fn(async()=>{throw new Error('UNEXPECTED_FALLBACK');});
  const page={goto:vi.fn(async()=>undefined),isClosed:()=>false,evaluate,close:vi.fn(async()=>undefined)};
  mocks.launch.mockResolvedValue({newPage:vi.fn(async()=>page),close:vi.fn(async()=>undefined)});
  const catalog=mode==='wrong-pin' ? {manifest:{packId:'freepats:upright-kw-small',packVersion:'2019-07-03.motif1'},manifestSha256:'b'.repeat(64),sample:()=>undefined} as any : undefined;
  const executor=new ChromiumRenderExecutor('/unused-test-root',catalog);
  await executor.start();
  try{
    const graph={...buildThirtySecondSpikeGraph(),schemaVersion:'audio-graph-spec.v2',engineVersion:'motif-forge-audio-engine.v2',tracks:[{kind:'multisample',instrumentPack:{packId:'freepats:upright-kw-small',packVersion:'2019-07-03.motif1',manifestSha256:'a'.repeat(64)}}]} as any;
    await expect(executor.render({requestVersion:'render-service-request.v1',requestId:'missing-pack',
      outputStorageKey:'jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/render.wav',maximumBytes:8640044,timeoutMs:1000,
      bridgeRequest:{requestVersion:'render-bridge-request.v1',requestId:'missing-pack',outputToken:'0'.repeat(32),outputBitDepth:24,graph}})).rejects.toThrow(mode==='missing'?'INSTRUMENT_PACK_UNAVAILABLE':'INSTRUMENT_MANIFEST_HASH_MISMATCH');
    expect(evaluate).not.toHaveBeenCalled();
  }finally{await executor.close();}
});
