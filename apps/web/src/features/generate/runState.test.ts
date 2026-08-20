import { describe, expect, it } from "vitest";

import type { AIRunStatus } from "../../shared/openapi";
import { initialRunState, reduceRunState } from "./runState";

const RUN_ID = "44444444-4444-4444-8444-444444444444";

function run(status: AIRunStatus, revisionId: string | null = null) {
  return {
    run_id: RUN_ID,
    status,
    revision_id: revisionId,
    progress: {
      phase: status,
      completed_export_steps: [],
      total_export_steps: 7,
      latest_event_sequence: 12,
      error_code: status === "failed" ? "RENDER_FAILED" : null,
    },
  };
}

describe("Run UI state reducer", () => {
  it("ignores duplicate and out-of-order events without regressing phase", () => {
    const waiting = reduceRunState(initialRunState, {
      type: "event",
      event: { sequence: 12, phase: "waiting_worker" },
    });
    const duplicate = reduceRunState(waiting, {
      type: "event",
      event: { sequence: 12, phase: "planning" },
    });
    const older = reduceRunState(duplicate, {
      type: "event",
      event: { sequence: 11, phase: "queued" },
    });

    expect(older.phase).toBe("waiting_worker");
    expect(older.lastSequence).toBe(12);
  });

  it("lets an authoritative GET replace the local phase after reconnect", () => {
    const local = { ...initialRunState, phase: "planning" as const, lastSequence: 9 };
    const recovered = reduceRunState(local, {
      type: "authoritative",
      run: run("waiting_approval"),
    });

    expect(recovered.phase).toBe("waiting_approval");
    expect(recovered.lastSequence).toBe(12);
  });

  it("derives partial_success when a failed Run retains a Revision", () => {
    const state = reduceRunState(initialRunState, {
      type: "authoritative",
      run: run("failed", "33333333-3333-4333-8333-333333333333"),
    });

    expect(state.phase).toBe("partial_success");
    expect(state.errorCode).toBe("RENDER_FAILED");
  });
});
