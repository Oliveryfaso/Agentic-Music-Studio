import { jsonHeaders, readData, requestJson } from "../../shared/api";
import type {
  CreateProjectInput,
  CreateProjectResult,
  ProjectSummary,
  ProjectWorkspace,
  RevisionStudio,
} from "../../shared/openapi";

export async function createProject(
  input: CreateProjectInput,
  idempotencyKey: string,
): Promise<CreateProjectResult> {
  const value = await requestJson("/api/v1/projects", {
    method: "POST",
    headers: jsonHeaders(idempotencyKey),
    body: JSON.stringify(input),
  });
  return readData<CreateProjectResult>(value);
}

export async function listProjects(limit = 50): Promise<ProjectSummary[]> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new RangeError("Project list limit must be between 1 and 50");
  }
  const value = await requestJson(`/api/v1/projects?limit=${limit}`);
  return readData<ProjectSummary[]>(value);
}

export async function readProject(projectId: string): Promise<ProjectWorkspace> {
  const value = await requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}`);
  return readData<ProjectWorkspace>(value);
}

export async function readRevisionStudio(
  projectId: string,
  revisionId: string,
): Promise<RevisionStudio> {
  const value = await requestJson(
    `/api/v1/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/studio`,
  );
  return readData<RevisionStudio>(value);
}
