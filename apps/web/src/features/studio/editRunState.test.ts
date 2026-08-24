import { describe, expect, it } from "vitest";

import { createEditRunState, reduceEditRunState } from "./editRunState";

describe("Edit Run state", () => {
  it("commits only from an authoritative readable Revision", () => {
    const state = reduceEditRunState(createEditRunState(), {
      type: "authoritative",
      run: {
        run_id: "run-1",
        status: "succeeded",
        revision_id: "22222222-2222-4222-8222-222222222222",
        progress: {
          phase: "succeeded", latest_event_sequence: 8,
          completed_export_steps: [], total_export_steps: 0, error_code: null,
        },
      },
    });
    expect(state.mode).toBe("committed");
    expect(state.revisionId).toBe("22222222-2222-4222-8222-222222222222");
  });

  it("preserves local drafts when the authoritative Base conflicts", () => {
    const state = reduceEditRunState(
      { ...createEditRunState(), draftCommands: [{ command_type: "move_clip" }] },
      { type: "conflict", serverRevisionId: "33333333-3333-4333-8333-333333333333" },
    );
    expect(state.mode).toBe("conflict");
    expect(state.draftCommands).toHaveLength(1);
  });
});
