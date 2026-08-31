import { readData, requestJson } from "../../shared/api";
import type { RunGraphReadModel, RunInspectionFacts } from "../../shared/openapi";

export async function readRunInspection(runId: string): Promise<RunInspectionFacts> {
  return readData<RunInspectionFacts>(await requestJson(
    `/api/v1/runs/${encodeURIComponent(runId)}/inspect`,
  ));
}

export async function readRunGraph(runId: string): Promise<RunGraphReadModel> {
  return readData<RunGraphReadModel>(await requestJson(
    `/api/v1/runs/${encodeURIComponent(runId)}/graph`,
  ));
}
