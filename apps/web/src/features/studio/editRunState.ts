import type { AIRun, AIRunEvent, EditorCommand, RunEditPreview } from "../../shared/openapi";

export type EditRunMode =
  | "idle" | "submitting" | "planning" | "rendering_preview"
  | "waiting_approval" | "committed" | "rejected" | "cancelled"
  | "failed" | "disconnected" | "conflict";

export interface EditRunViewState {
  mode: EditRunMode;
  runId: string | null;
  revisionId: string | null;
  preview: RunEditPreview | null;
  errorCode: string | null;
  lastSequence: number;
  serverRevisionId: string | null;
  draftCommands: Array<EditorCommand | Record<string, unknown>>;
}

export type EditRunAction =
  | { type: "submitting" }
  | { type: "authoritative"; run: Pick<AIRun, "status" | "revision_id" | "edit_preview" | "run_id" | "progress"> }
  | { type: "event"; event: AIRunEvent }
  | { type: "disconnected"; errorCode?: string }
  | { type: "conflict"; serverRevisionId: string }
  | { type: "reset" };

export function createEditRunState(): EditRunViewState {
  return {
    mode: "idle", runId: null, revisionId: null, preview: null,
    errorCode: null, lastSequence: 0, serverRevisionId: null, draftCommands: [],
  };
}

export function reduceEditRunState(
  state: EditRunViewState,
  action: EditRunAction,
): EditRunViewState {
  if (action.type === "reset") return createEditRunState();
  if (action.type === "submitting") return { ...state, mode: "submitting", errorCode: null };
  if (action.type === "disconnected") {
    return { ...state, mode: "disconnected", errorCode: action.errorCode ?? null };
  }
  if (action.type === "conflict") {
    return { ...state, mode: "conflict", serverRevisionId: action.serverRevisionId };
  }
  if (action.type === "event") {
    if (action.event.sequence <= state.lastSequence) return state;
    return { ...state, lastSequence: action.event.sequence };
  }
  const mode = modeFor(action.run);
  return {
    ...state,
    mode,
    runId: action.run.run_id ?? state.runId,
    revisionId: action.run.revision_id ?? null,
    preview: action.run.edit_preview ?? null,
    errorCode: action.run.progress.error_code ?? null,
    lastSequence: Math.max(state.lastSequence, action.run.progress.latest_event_sequence),
  };
}

function modeFor(run: Pick<AIRun, "status" | "revision_id" | "edit_preview">): EditRunMode {
  if (run.status === "succeeded") return run.revision_id ? "committed" : "failed";
  if (run.status === "waiting_edit_approval") return "waiting_approval";
  if (run.status === "waiting_worker") return "rendering_preview";
  if (run.status === "rejected") return "rejected";
  if (run.status === "cancelled") return "cancelled";
  if (run.status === "failed") return "failed";
  return "planning";
}
