import { afterEach, describe, expect, it, vi } from "vitest";

import { createEditRun, decideEditPreview } from "./editRunApi";

afterEach(() => vi.unstubAllGlobals());

describe("Edit Run API", () => {
  it("sends bounded selection identity and the durable decision key", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify({ data: { run_id: "run-1" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    await createEditRun("project-1", {
      branch_id: "branch-1",
      base_revision_id: "revision-1",
      run_type: "edit",
      brief: null,
      edit_request: {
        intent: "lower the Pad",
        selection: { track_ids: ["track-1"], start_tick: 0, end_tick: 1920 },
        locked_ranges: [], allow_local_catalog: true, seed: 0,
      },
      max_model_requests: 1,
      max_total_tokens: 4000,
    }, "edit-create-key");
    await decideEditPreview("run-1", {
      action: "approve", preview_id: "preview-1",
      expected_candidate_content_hash: "a".repeat(64), actor_id: "human:web",
      approval_assertion: "I approve this rendered edit.", note: "",
    }, "edit-decision-key");

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toMatchObject({
      run_type: "edit",
      edit_request: { selection: { track_ids: ["track-1"], start_tick: 0, end_tick: 1920 } },
    });
    expect(new Headers(fetch.mock.calls[1]?.[1]?.headers).get("Idempotency-Key"))
      .toBe("edit-decision-key");
  });
});
