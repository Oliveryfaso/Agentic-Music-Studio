import { expect,it } from "vitest";
import { assertPianoProbeResult } from "./fixtures/piano-probe-acceptance.js";
const valid={baseHz:1800,octaveHz:3600,energyRatio:4,releasedAfterStop:0,
  newVoiceSurvivesOldRelease:.01,allVoicesStopped:0};
it("accepts positive finite octave and velocity evidence",()=>{
  expect(()=>assertPianoProbeResult(valid)).not.toThrow();
});
it("rejects silent non-loop voices even if the loop retrigger still works",()=>{
  expect(()=>assertPianoProbeResult({...valid,baseHz:0,octaveHz:0,energyRatio:NaN})).toThrow("PIANO_ADAPTER_PROBE_FAILED");
});
it("checks measurement numbers while permitting descriptive probe metadata",()=>{
  const result={...valid,fixture:"self-authored click, not piano"};
  expect(()=>assertPianoProbeResult(result)).not.toThrow();
});
