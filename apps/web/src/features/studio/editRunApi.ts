import { ApiError, jsonHeaders, readData, requestJson } from "../../shared/api";
import type {
  AIRun,
  CreateAIRunInput,
  EditPreviewDecisionInput,
  RunActionInput,
} from "../../shared/openapi";

export async function readEditRun(runId: string): Promise<AIRun> {
  return readData<AIRun>(await requestJson(`/api/v1/runs/${encodeURIComponent(runId)}`));
}

export async function createEditRun(
  projectId: string,
  input: CreateAIRunInput,
  idempotencyKey: string,
): Promise<AIRun> {
  return readData<AIRun>(await requestJson(
    `/api/v1/projects/${encodeURIComponent(projectId)}/ai-runs`,
    { method: "POST", headers: jsonHeaders(idempotencyKey), body: JSON.stringify(input) },
  ));
}

export async function decideEditPreview(
  runId: string,
  input: EditPreviewDecisionInput,
  idempotencyKey: string,
): Promise<AIRun> {
  return editAction(runId, "edit-decision", input, idempotencyKey);
}

export async function cancelEditRun(
  runId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<AIRun> {
  return editAction(
    runId,
    "cancel",
    { expected_version: expectedVersion } satisfies RunActionInput,
    idempotencyKey,
  );
}

async function editAction(
  runId: string,
  action: "edit-decision" | "cancel",
  input: EditPreviewDecisionInput | RunActionInput,
  idempotencyKey: string,
): Promise<AIRun> {
  try {
    return readData<AIRun>(await requestJson(
      `/api/v1/runs/${encodeURIComponent(runId)}/${action}`,
      { method: "POST", headers: jsonHeaders(idempotencyKey), body: JSON.stringify(input) },
    ));
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      throw new ApiError(
        "编辑 Base 已变化；本地 Draft 已保留，请刷新后重新确认。",
        error.code,
        false,
        error.status,
      );
    }
    throw error;
  }
}
