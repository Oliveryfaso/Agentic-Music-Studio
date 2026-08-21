import { ApiError, jsonHeaders, readData, requestJson } from "../../shared/api";
import type {
  AIRun,
  CreateAIRunInput,
  ReplanAIRunInput,
  ResumeAIRunInput,
  RunActionInput,
  SelectCandidateInput,
} from "../../shared/openapi";

export class RunActionConflict extends ApiError {
  constructor(error: ApiError, readonly authoritativeRun: AIRun) {
    super(error.message, error.code, error.retryable, error.status);
    this.name = "RunActionConflict";
  }
}

export async function readRun(runId: string): Promise<AIRun> {
  return readData<AIRun>(
    await requestJson(`/api/v1/runs/${encodeURIComponent(runId)}`),
  );
}

export async function createRun(
  projectId: string,
  input: CreateAIRunInput,
  idempotencyKey: string,
): Promise<AIRun> {
  const value = await requestJson(
    `/api/v1/projects/${encodeURIComponent(projectId)}/ai-runs`,
    {
      method: "POST",
      headers: jsonHeaders(idempotencyKey),
      body: JSON.stringify(input),
    },
  );
  return readData<AIRun>(value);
}

export async function resumeRun(
  runId: string,
  input: ResumeAIRunInput,
  idempotencyKey: string,
): Promise<AIRun> {
  return runAction(runId, "resume", input, idempotencyKey);
}

export async function cancelRun(
  runId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<AIRun> {
  return runAction(
    runId,
    "cancel",
    { expected_version: expectedVersion } satisfies RunActionInput,
    idempotencyKey,
  );
}

export async function retryRun(
  runId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<AIRun> {
  return runAction(
    runId,
    "retry",
    { expected_version: expectedVersion } satisfies RunActionInput,
    idempotencyKey,
  );
}

export async function replanRun(
  runId: string,
  input: ReplanAIRunInput,
  idempotencyKey: string,
): Promise<AIRun> {
  return runAction(runId, "replan", input, idempotencyKey);
}

export async function selectCandidate(
  runId: string,
  input: SelectCandidateInput,
  idempotencyKey: string,
): Promise<AIRun> {
  return runAction(runId, "select-candidate", input, idempotencyKey);
}

async function runAction(
  runId: string,
  action: "resume" | "cancel" | "retry" | "replan" | "select-candidate",
  input: ResumeAIRunInput | ReplanAIRunInput | RunActionInput | SelectCandidateInput,
  idempotencyKey: string,
): Promise<AIRun> {
  try {
    const value = await requestJson(
      `/api/v1/runs/${encodeURIComponent(runId)}/${action}`,
      {
        method: "POST",
        headers: jsonHeaders(idempotencyKey),
        body: JSON.stringify(input),
      },
    );
    return readData<AIRun>(value);
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      throw new RunActionConflict(error, await readRun(runId));
    }
    throw error;
  }
}
