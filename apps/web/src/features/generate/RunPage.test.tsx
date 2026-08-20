import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunPage } from "./RunPage";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const BRANCH_ID = "22222222-2222-4222-8222-222222222222";
const BASE_REVISION_ID = "33333333-3333-4333-8333-333333333333";
const REVISION_ID = "44444444-4444-4444-8444-444444444444";
const RUN_ID = "55555555-5555-4555-8555-555555555555";
const CHILD_RUN_ID = "66666666-6666-4666-8666-666666666666";
const PLAN_HASH = "a".repeat(64);
const ASSERTION = "I reviewed this exact composition plan and approve it.";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("Plan review and persistent Run progress", () => {
  it("reads the authoritative fallback Plan, approves its exact version/hash, and opens Studio after terminal recovery", async () => {
    let approved = false;
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/runs/${RUN_ID}` && init?.method !== "POST") {
        return jsonResponse({ data: approved ? runData("succeeded", { revisionId: REVISION_ID }) : runData("waiting_approval", { plan: true }) });
      }
      if (path === `/api/v1/runs/${RUN_ID}/events`) {
        return new Response(new ReadableStream<Uint8Array>({
          start(controller) { streamController = controller; },
        }), { headers: { "Content-Type": "text/event-stream" } });
      }
      if (path === `/api/v1/runs/${RUN_ID}/resume` && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        if (
          body.expected_version !== 3 ||
          body.expected_plan_hash !== PLAN_HASH ||
          body.actor_id !== "portfolio-owner" ||
          body.approval_assertion !== ASSERTION ||
          body.decision !== "approve"
        ) {
          return jsonResponse({ detail: "approval mismatch", error_code: "APPROVAL_MISMATCH" }, 422);
        }
        approved = true;
        queueMicrotask(() => {
          streamController?.enqueue(new TextEncoder().encode(sseEvent(13, "succeeded")));
          streamController?.close();
        });
        return jsonResponse({ data: runData("materializing") });
      }
      if (path === `/api/v1/projects/${PROJECT_ID}`) {
        return jsonResponse({ data: projectWorkspace() });
      }
      throw new Error(`unexpected request ${path}`);
    }));

    render(<RunPage runId={RUN_ID} />);

    expect(await screen.findByText("Fallback Plan · 仍需人工审批")).toBeInTheDocument();
    expect(screen.getByText("72 BPM")).toBeInTheDocument();
    expect(screen.getByText("D dorian")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Opening" })).toBeInTheDocument();
    expect(screen.getByText("能量 25%")).toBeInTheDocument();
    expect(screen.getByText("Warm Pad")).toBeInTheDocument();
    expect(screen.getByText("Use slow spectral motion and restrained density")).toBeInTheDocument();
    expect(screen.queryByText("deepseek-v4-flash")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("审批人"), { target: { value: "portfolio-owner" } });
    fireEvent.change(screen.getByLabelText("审批确认"), { target: { value: ASSERTION } });
    expect(screen.getByRole("button", { name: "批准并生成" })).toBeVisible();
    expect(screen.getByRole("button", { name: "拒绝计划" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "批准并生成" }));

    expect(await screen.findByText("作品已生成并写入 Revision")).toBeInTheDocument();
    expect(sessionStorage.length).toBe(1);
    expect(sessionStorage.getItem(`motif-forge:run:${RUN_ID}:last-sequence`)).toBe("13");
    expect(JSON.stringify(sessionStorage)).not.toContain(ASSERTION);
    fireEvent.click(await screen.findByRole("button", { name: "打开只读 Studio" }));
    expect(window.location.pathname).toBe(`/projects/${PROJECT_ID}/studio/${REVISION_ID}`);
  });

  it("creates an immutable child adjustment Run while preserving the displayed parent Plan", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/runs/${RUN_ID}`) return jsonResponse({ data: runData("waiting_approval", { plan: true }) });
      if (path === `/api/v1/runs/${RUN_ID}/events`) return pendingEventStream();
      if (path === `/api/v1/runs/${RUN_ID}/replan` && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        const adjustment = body.adjustment as Record<string, unknown>;
        if (
          body.expected_version !== 3 ||
          body.expected_plan_hash !== PLAN_HASH ||
          adjustment.schema_version !== "plan-adjustment.v1" ||
          adjustment.target_bpm !== 78 ||
          adjustment.note !== "Increase forward motion without changing the opening."
        ) {
          return jsonResponse({ detail: "adjustment mismatch", error_code: "ADJUSTMENT_MISMATCH" }, 422);
        }
        return jsonResponse({ data: runData("queued", { runId: CHILD_RUN_ID, parentRunId: RUN_ID }) }, 202);
      }
      throw new Error(`unexpected request ${path}`);
    }));

    render(<RunPage runId={RUN_ID} />);
    expect(await screen.findByRole("heading", { name: "Opening" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("调整后的 BPM"), { target: { value: "78" } });
    fireEvent.change(screen.getByLabelText("调整说明"), {
      target: { value: "Increase forward motion without changing the opening." },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建调整后的 Plan" }));

    await waitFor(() => expect(window.location.pathname).toBe(`/runs/${CHILD_RUN_ID}`));
    expect(screen.getByRole("heading", { name: "Opening" })).toBeInTheDocument();
  });

  it("keeps reject, cancel conflict, retry, cancelled, failure, and partial-success actions safe", async () => {
    let current = runData("waiting_approval", { plan: true });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/runs/${RUN_ID}`) return jsonResponse({ data: current });
      if (path === `/api/v1/runs/${RUN_ID}/events`) return pendingEventStream();
      if (path === `/api/v1/runs/${RUN_ID}/resume` && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        if (body.decision !== "reject" || body.approval_assertion !== ASSERTION) {
          return jsonResponse({ detail: "reject mismatch", error_code: "REJECT_MISMATCH" }, 422);
        }
        current = runData("rejected");
        return jsonResponse({ data: current });
      }
      if (path === `/api/v1/runs/${RUN_ID}/cancel` && init?.method === "POST") {
        current = runData("failed", { revisionId: REVISION_ID, version: 5 });
        return jsonResponse({ detail: "stale Run version", error_code: "AI_RUN_ACTION_STATE_CONFLICT" }, 409);
      }
      if (path === `/api/v1/runs/${RUN_ID}/retry` && init?.method === "POST") {
        return jsonResponse({ data: runData("queued", { runId: CHILD_RUN_ID, parentRunId: RUN_ID }) }, 202);
      }
      if (path === `/api/v1/projects/${PROJECT_ID}`) return jsonResponse({ data: projectWorkspace() });
      throw new Error(`unexpected request ${path}`);
    }));

    const first = render(<RunPage runId={RUN_ID} />);
    await screen.findByRole("button", { name: "拒绝计划" });
    fireEvent.change(screen.getByLabelText("审批人"), { target: { value: "portfolio-owner" } });
    fireEvent.change(screen.getByLabelText("审批确认"), { target: { value: ASSERTION } });
    fireEvent.click(screen.getByRole("button", { name: "拒绝计划" }));
    expect(await screen.findByText("计划已拒绝")).toBeInTheDocument();

    first.unmount();
    current = runData("waiting_worker", { version: 4 });
    const second = render(<RunPage runId={RUN_ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "取消 Run" }));
    expect(await screen.findByText("Run 状态已由服务端更新")).toBeInTheDocument();
    expect(screen.getByText("已有安全 Revision，导出未完整完成")).toBeInTheDocument();

    second.unmount();
    current = runData("failed");
    const third = render(<RunPage runId={RUN_ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "重试为新 Run" }));
    await waitFor(() => expect(window.location.pathname).toBe(`/runs/${CHILD_RUN_ID}`));

    third.unmount();
    current = runData("cancelled");
    render(<RunPage runId={RUN_ID} />);
    expect(await screen.findByText("Run 已取消")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试为新 Run" })).toBeInTheDocument();
  });
});

function runData(
  status: "queued" | "waiting_approval" | "materializing" | "waiting_worker" | "succeeded" | "rejected" | "failed" | "cancelled",
  options: {
    runId?: string;
    parentRunId?: string | null;
    revisionId?: string | null;
    version?: number;
    plan?: boolean;
  } = {},
) {
  return {
    run_id: options.runId ?? RUN_ID,
    parent_run_id: options.parentRunId ?? null,
    project_id: PROJECT_ID,
    branch_id: BRANCH_ID,
    base_revision_id: BASE_REVISION_ID,
    thread_id: `generate-${options.runId ?? RUN_ID}`,
    status,
    version: options.version ?? 3,
    pending_action: status === "waiting_approval" ? "approve_plan" : null,
    pending_plan_id: options.plan ? "77777777-7777-4777-8777-777777777777" : null,
    pending_plan_hash: options.plan ? PLAN_HASH : null,
    submitted_model_requests: 1,
    max_model_requests: 1,
    prompt_tokens: 120,
    completion_tokens: 240,
    total_tokens: 360,
    model_usage_status: "known",
    cost_status: "unknown",
    cost_amount_microusd: null,
    cost_pricing_version: null,
    revision_id: options.revisionId ?? null,
    bundle_id: status === "succeeded" ? "88888888-8888-4888-8888-888888888888" : null,
    fallback_reason: options.plan ? "provider unavailable" : null,
    error_code: status === "failed" ? "RENDER_FAILED" : null,
    plan: options.plan ? planProjection() : null,
    progress: {
      phase: status,
      completed_export_steps: status === "succeeded" ? ["master", "stem-pad", "stem-melody", "stem-bass", "stem-rhythm", "delivery-mp3", "bundle"] : [],
      total_export_steps: 7,
      latest_event_sequence: status === "succeeded" ? 13 : 3,
      error_code: status === "failed" ? "RENDER_FAILED" : null,
    },
  };
}

function planProjection() {
  return {
    plan_id: "77777777-7777-4777-8777-777777777777",
    content_hash: PLAN_HASH,
    hash_version: "composition-plan-hash.lossless-v2",
    provider: "deepseek",
    model: "deepseek-v4-flash",
    fallback_reason: "provider unavailable",
    plan: {
      schema_version: "composition-plan.v1",
      genre: "synth_ambient",
      era_influences: ["modern ambient"],
      purpose: "Instrumental background for a science-fiction puzzle",
      moods: ["weightless", "curious"],
      duration_bars: 32,
      bpm: 72,
      meter: "4/4",
      key: { tonic: "D", mode: "dorian" },
      sections: [
        { section_id: "opening", name: "Opening", start_bar: 0, end_bar: 8, function: "Establish the harmonic field", energy: 0.25 },
        { section_id: "development", name: "Development", start_bar: 8, end_bar: 24, function: "Develop the pulse and motif", energy: 0.6 },
        { section_id: "resolution", name: "Resolution", start_bar: 24, end_bar: 32, function: "Reduce density and resolve", energy: 0.2 },
      ],
      instrumentation: [
        { instrument_id: "warm_pad", name: "Warm Pad", role: "harmonic bed", pitch_range: "low-mid to high-mid", entry_section_id: "opening", exit_section_id: "resolution" },
        { instrument_id: "soft_pulse", name: "Soft Pulse", role: "rhythmic motion", pitch_range: "mid", entry_section_id: "development", exit_section_id: "resolution" },
      ],
      harmonic_language: "Open fifths with restrained D dorian color tones",
      rhythmic_language: "Sparse eighth-note pulses with gradual subdivision",
      texture: "Layered pads with a narrow pulse and long controlled tails",
      hard_constraints: ["avoid clipping"],
      soft_preferences: ["leave room for narration"],
      negative_constraints: ["no abrupt drop"],
      knowledge_references: [{ reference_id: "style:synth-ambient:v1", summary: "Use slow spectral motion and restrained density", confidence: 0.9 }],
      confidence: 0.88,
    },
  };
}

function projectWorkspace() {
  return {
    project_id: PROJECT_ID,
    name: "Orbital Glass",
    status: "active",
    updated_at: "2026-08-20T08:00:00Z",
    active_branch_id: BRANCH_ID,
    head_revision_id: REVISION_ID,
    revisions: [],
    runs: [],
    recoverable_run: null,
    storage_root_status: "ready",
  };
}

function sseEvent(sequence: number, phase: string): string {
  return `id: ${sequence}\nevent: ai_run.${phase}\ndata: ${JSON.stringify({
    sequence,
    event_id: "99999999-9999-4999-8999-999999999999",
    run_id: RUN_ID,
    event_type: `ai_run.${phase}`,
    phase,
    payload: { status: phase },
    dedupe_key: phase,
    created_at: "2026-08-20T10:00:00Z",
  })}\n\n`;
}

function pendingEventStream(): Response {
  return new Response(new ReadableStream<Uint8Array>({ start() {} }), {
    headers: { "Content-Type": "text/event-stream" },
  });
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
