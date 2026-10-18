import { describe, expect, it } from "vitest";
import { estimateRenderCapacity } from "../src/capacity.js";
import { buildThirtySecondSpikeGraph } from "../src/spike-fixture.js";

describe("render-capacity.v1", () => {
  it.each([
    [30,48000,24,0,8_640_044], [300,48000,24,0,86_400_044],
    [30,44100,16,2,5_644_844], [0.10001,48000,24,0,28_850],
  ])("derives PCM size with explicit tail and ceiling (%s/%s/%s/%s)", (duration,rate,depth,tail,want) => {
    const graph={...buildThirtySecondSpikeGraph(),durationSeconds:duration!,sampleRate:rate as 44100|48000};
    const budget=estimateRenderCapacity(graph,depth as 16|24,tail);
    expect(budget.wavBytes).toBe(want);
    expect(budget.workingBufferBytes).toBeLessThanOrEqual(320*1024**2);
  });
  it.each([NaN,Infinity,-1,301])("rejects invalid duration %s", duration => {
    expect(()=>estimateRenderCapacity({...buildThirtySecondSpikeGraph(),durationSeconds:duration})).toThrow("RENDER_CAPACITY_INVALID");
  });
  it("does not append implicit reverb decay", () => {
    const graph={...buildThirtySecondSpikeGraph(),reverbDecaySeconds:8};
    expect(estimateRenderCapacity(graph).wavBytes).toBe(8_640_044);
    expect(()=>estimateRenderCapacity({...graph,durationSeconds:300},24,1)).toThrow("RENDER_CAPACITY_INVALID");
  });
});
