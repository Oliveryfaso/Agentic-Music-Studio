import { readData, requestJson } from "../../shared/api";
import type { RevisionExportProjection } from "../../shared/openapi";

export async function readRevisionExport(
  projectId: string,
  revisionId: string,
): Promise<RevisionExportProjection> {
  return readData<RevisionExportProjection>(await requestJson(
    `/api/v1/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/exports`,
  ));
}
