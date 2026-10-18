export type PianoProbeMeasurements = Readonly<{
  baseHz:number; octaveHz:number; energyRatio:number; releasedAfterStop:number;
  newVoiceSurvivesOldRelease:number; allVoicesStopped:number;
}>;
// Shared by the real browser probe and its false-positive regression.
export function assertPianoProbeResult(result:PianoProbeMeasurements):void {
  if(![result.baseHz,result.octaveHz,result.energyRatio,result.releasedAfterStop,
    result.newVoiceSurvivesOldRelease,result.allVoicesStopped].every(Number.isFinite) || result.baseHz<=0 || result.octaveHz<=0 ||
    result.energyRatio<=0 || Math.abs(result.octaveHz/result.baseHz-2)>.1 || Math.abs(result.energyRatio-4)>.01 ||
    result.releasedAfterStop!==0 || result.newVoiceSurvivesOldRelease<=1e-9 || result.allVoicesStopped!==0)
    throw new Error("PIANO_ADAPTER_PROBE_FAILED");
}
