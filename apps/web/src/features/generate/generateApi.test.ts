import { afterEach, describe, expect, it, vi } from "vitest";

import { cancelRun, readRun } from "./generateApi";

const RUN_ID = "44444444-4444-4444-8444-444444444444";

function runData(status = "waiting_approval") {
  return {
    run_id: RUN_ID,
    parent_run_id: null,
    project_id: "11111111-1111-4111-8111-111111111111",
    branch_id: "22222222-2222-4222-8222-222222222222",
    base_revision_id: "33333333-3333-4333-8333-333333333333",
    thread_id: "generate-web-test",
    status,
    version: 3,
    pending_action: status === "waiting_approval" ? "approve_plan" : null,
    pending_plan_id: null,
    pending_plan_hash: null,
    submitted_model_requests: 1,
    max_model_requests: 1,
    prompt_tokens: 100,
    completion_tokens: 200,
    total_tokens: 300,
    model_usage_status: "known",
    cost_status: "unknown",
    cost_amount_microusd: null,
    cost_pricing_version: null,
    revision_id: null,
    bundle_id: null,
    fallback_reason: null,
    error_code: null,
    plan: null,
    progress: {
      phase: status,
      completed_export_steps: [],
      total_export_steps: 7,
      latest_event_sequence: 3,
      error_code: null,
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("generated Generate API client", () => {
  it("reloads authoritative Run state after a stale action conflict", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: "stale Run version",
        error_code: "AI_RUN_ACTION_STATE_CONFLICT",
        retryable: false,
      }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: runData() })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(cancelRun(RUN_ID, 2, "cancel-key-001")).rejects.toMatchObject({
      status: 409,
      authoritativeRun: { version: 3 },
    });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `/api/v1/runs/${RUN_ID}/cancel`,
      `/api/v1/runs/${RUN_ID}`,
    ]);
  });

  it("reads the generated Run projection without a handwritten DTO", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: runData("waiting_worker") })),
    ));

    const run = await readRun(RUN_ID);

    expect(run.progress.total_export_steps).toBe(7);
    expect(run.progress.phase).toBe("waiting_worker");
  });
});
