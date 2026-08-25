import { readData, requestJson } from "../../shared/api";
import type { RunInspectionFacts } from "../../shared/openapi";

export async function readRunInspection(runId: string): Promise<RunInspectionFacts> {
  return readData<RunInspectionFacts>(await requestJson(
    `/api/v1/runs/${encodeURIComponent(runId)}/inspect`,
  ));
}
