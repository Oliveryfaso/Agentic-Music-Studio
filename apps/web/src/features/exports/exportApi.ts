import { readData, requestJson } from "../../shared/api";
import type { RevisionExportProjection, RevisionExportOptions, RevisionExportRun } from "../../shared/openapi";

export async function readRevisionExport(
  projectId: string,
  revisionId: string,
  planHash?: string,
): Promise<RevisionExportProjection> {
  return readData<RevisionExportProjection>(await requestJson(
    `/api/v1/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/exports${planHash ? `?plan_hash=${encodeURIComponent(planHash)}` : ""}`,
  ));
}


export async function startRevisionExport(projectId: string, revisionId: string, options: Partial<RevisionExportOptions>, key: string): Promise<RevisionExportRun> {
  return readData<RevisionExportRun>(await requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/exports`, {
    method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(options),
  }));
}

export async function cancelRevisionExport(projectId: string, revisionId: string, threadId: string): Promise<RevisionExportRun> {
  return readData<RevisionExportRun>(await requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/export-runs/${encodeURIComponent(threadId)}/cancel`, { method: "POST" }));
}
