import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BriefPage } from "./BriefPage";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const BRANCH_ID = "22222222-2222-4222-8222-222222222222";
const REVISION_ID = "33333333-3333-4333-8333-333333333333";
const RUN_ID = "44444444-4444-4444-8444-444444444444";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("New Composition Brief", () => {
  it("keeps an invalid instrumental Brief local and navigates after a valid public Run create", async () => {
    let createRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${PROJECT_ID}`) {
        return jsonResponse({ data: projectWorkspace() });
      }
      if (path === `/api/v1/projects/${PROJECT_ID}/ai-runs` && init?.method === "POST") {
        createRequests += 1;
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        const brief = body.brief as Record<string, unknown>;
        if (
          body.branch_id !== BRANCH_ID ||
          body.base_revision_id !== REVISION_ID ||
          body.max_model_requests !== 1 ||
          brief.schema_version !== "composition-brief.v1" ||
          brief.style !== "classical_chamber" ||
          brief.purpose !== "Instrumental background for a science-fiction puzzle" ||
          !Array.isArray(brief.moods) ||
          brief.moods.join(",") !== "weightless,curious"
        ) {
          return jsonResponse({ detail: "invalid Brief payload", error_code: "BRIEF_INVALID" }, 422);
        }
        return jsonResponse({ data: runData("queued") }, 202);
      }
      throw new Error(`unexpected request ${path}`);
    }));

    renderPage();
    expect(await screen.findByRole("heading", { name: "定义这首作品" })).toBeInTheDocument();
    const strategy = screen.getByLabelText("音乐策略");
    expect(Array.from(strategy.querySelectorAll("option")).map((option) => option.textContent)).toEqual([
      "Synth Ambient",
      "Minimal Electronic",
      "Classical Chamber",
      "Jazz Harmony & Improvisation",
    ]);

    fillBrief("需要人声演唱的科幻背景");
    fireEvent.click(screen.getByRole("button", { name: "提交 Brief 并规划" }));
    expect(await screen.findByText("首版只支持纯器乐，请移除人声或演唱要求。")).toBeInTheDocument();
    expect(createRequests).toBe(0);

    fireEvent.change(screen.getByLabelText("用途"), {
      target: { value: "Instrumental background for a science-fiction puzzle" },
    });
    fireEvent.change(screen.getByLabelText("音乐策略"), {
      target: { value: "classical_chamber" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交 Brief 并规划" }));

    await screen.findByText("Run 已进入持久队列");
    expect(createRequests).toBe(1);
    expect(window.location.pathname).toBe(`/runs/${RUN_ID}`);
  });

  it("keeps core intent visible and preserves advanced values through disclosure and validation", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === `/api/v1/projects/${PROJECT_ID}`) return jsonResponse({ data: projectWorkspace() });
      throw new Error(`unexpected request ${String(input)}`);
    }));
    renderPage();

    expect(await screen.findByLabelText("作品标题")).toBeVisible();
    expect(screen.getByLabelText("音乐策略")).toBeVisible();
    expect(screen.getByLabelText("用途")).toBeVisible();
    expect(screen.getByLabelText("情绪")).toBeVisible();
    expect(screen.getByLabelText("目标时长（秒）")).toBeVisible();
    const advanced = screen.getByText("高级编曲约束").closest("details")!;
    expect(advanced).not.toHaveAttribute("open");

    fireEvent.click(screen.getByText("高级编曲约束"));
    fireEvent.change(screen.getByLabelText("目标 BPM"), { target: { value: "999" } });
    fireEvent.click(screen.getByText("高级编曲约束"));
    fireEvent.click(screen.getByText("高级编曲约束"));
    expect(screen.getByLabelText("目标 BPM")).toHaveValue(999);
    fireEvent.click(screen.getByText("高级编曲约束"));

    fireEvent.change(screen.getByLabelText("作品标题"), { target: { value: "Orbital Glass" } });
    fireEvent.change(screen.getByLabelText("用途"), { target: { value: "Instrumental score" } });
    fireEvent.change(screen.getByLabelText("情绪"), { target: { value: "weightless" } });
    fireEvent.click(screen.getByRole("button", { name: "提交 Brief 并规划" }));
    expect(await screen.findByText("BPM 需在 40–220 之间。")).toBeInTheDocument();
    expect(advanced).toHaveAttribute("open");
    expect(screen.getByLabelText("目标 BPM")).toHaveFocus();
  });
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BriefPage projectId={PROJECT_ID} />
    </QueryClientProvider>,
  );
}

function fillBrief(purpose: string) {
  fireEvent.change(screen.getByLabelText("作品标题"), { target: { value: "Orbital Glass" } });
  fireEvent.change(screen.getByLabelText("用途"), { target: { value: purpose } });
  fireEvent.change(screen.getByLabelText("情绪"), { target: { value: "weightless, curious" } });
  fireEvent.change(screen.getByLabelText("偏好乐器"), { target: { value: "warm pad, soft pulse" } });
  fireEvent.change(screen.getByLabelText("目标 BPM"), { target: { value: "72" } });
  fireEvent.change(screen.getByLabelText("目标调性"), { target: { value: "D dorian" } });
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

function runData(status: "queued") {
  return {
    run_id: RUN_ID,
    parent_run_id: null,
    project_id: PROJECT_ID,
    branch_id: BRANCH_ID,
    base_revision_id: REVISION_ID,
    thread_id: "generate-brief-test",
    status,
    version: 0,
    pending_action: null,
    pending_plan_id: null,
    pending_plan_hash: null,
    submitted_model_requests: 0,
    max_model_requests: 1,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    model_usage_status: "unknown",
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
      latest_event_sequence: 1,
      error_code: null,
    },
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
