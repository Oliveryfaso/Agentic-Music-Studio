import type { AIRun, AIRunEvent } from "../../shared/openapi";

export type GeneratePhase =
  | "draft"
  | "submitting"
  | "queued"
  | "planning"
  | "waiting_approval"
  | "approving"
  | "rejecting"
  | "adjusting"
  | "child_queued"
  | "child_planning"
  | "child_waiting_approval"
  | "materializing"
  | "waiting_worker"
  | "succeeded"
  | "rejected"
  | "cancelled"
  | "failed"
  | "partial_success";

export type RunConnectionState =
  | "initial_read"
  | "connecting"
  | "live"
  | "reconnecting"
  | "replaying"
  | "terminal_closed"
  | "offline_error";

export interface RunUiState {
  phase: GeneratePhase;
  connection: RunConnectionState;
  lastSequence: number;
  errorCode: string | null;
}

export const initialRunState: RunUiState = {
  phase: "draft",
  connection: "initial_read",
  lastSequence: 0,
  errorCode: null,
};

type RunProjection = Pick<AIRun, "progress" | "revision_id" | "run_id" | "status">;
type RunEventProjection = Pick<AIRunEvent, "phase" | "sequence">;

export type RunStateAction =
  | { type: "event"; event: RunEventProjection }
  | { type: "authoritative"; run: RunProjection }
  | { type: "connection"; connection: RunConnectionState };

const PHASES = new Set<GeneratePhase>([
  "draft",
  "submitting",
  "queued",
  "planning",
  "waiting_approval",
  "approving",
  "rejecting",
  "adjusting",
  "child_queued",
  "child_planning",
  "child_waiting_approval",
  "materializing",
  "waiting_worker",
  "succeeded",
  "rejected",
  "cancelled",
  "failed",
  "partial_success",
]);

const TERMINAL_PHASES = new Set<GeneratePhase>([
  "succeeded",
  "rejected",
  "cancelled",
  "failed",
  "partial_success",
]);

export function reduceRunState(state: RunUiState, action: RunStateAction): RunUiState {
  if (action.type === "connection") {
    return { ...state, connection: action.connection };
  }
  if (action.type === "event") {
    if (action.event.sequence <= state.lastSequence) return state;
    const phase = toGeneratePhase(action.event.phase) ?? state.phase;
    return {
      ...state,
      phase,
      connection: TERMINAL_PHASES.has(phase) ? "terminal_closed" : "live",
      lastSequence: action.event.sequence,
    };
  }

  const phase = authoritativePhase(action.run);
  return {
    phase,
    connection: TERMINAL_PHASES.has(phase) ? "terminal_closed" : state.connection,
    lastSequence: action.run.progress.latest_event_sequence,
    errorCode: action.run.progress.error_code,
  };
}

function authoritativePhase(run: RunProjection): GeneratePhase {
  if (run.status === "failed" && run.revision_id !== null && run.revision_id !== undefined) {
    return "partial_success";
  }
  return toGeneratePhase(run.progress.phase) ?? toGeneratePhase(run.status) ?? "failed";
}

function toGeneratePhase(value: string): GeneratePhase | null {
  return PHASES.has(value as GeneratePhase) ? (value as GeneratePhase) : null;
}
