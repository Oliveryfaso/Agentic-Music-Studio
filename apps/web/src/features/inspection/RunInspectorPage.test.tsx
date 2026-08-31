import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { RunGraphReadModel, RunInspectionFacts } from "../../shared/openapi";
import { RunInspectorPage } from "./RunInspectorPage";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const REVISION_ID = "33333333-3333-4333-8333-333333333333";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows graph versions, budgets, decisions, outputs, and ordered events", async () => {
  stubApi(inspection(), graph());
  renderPage();

  const graphView = await screen.findByLabelText("Generate Parent Graph 执行路径");
  const timeline = screen.getByText("Graph Timeline").closest("details");
  expect(graphView.compareDocumentPosition(timeline!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  expect(screen.getByText("ValidateRequest")).toBeInTheDocument();
  expect(screen.getByText("0 / 3 model requests")).toBeInTheDocument();
  expect(screen.getAllByTestId("inspection-event").map((node) => node.dataset.sequence)).toEqual(["1", "2", "3"]);
  expect(screen.getByText("Plan · approve")).toBeInTheDocument();
  expect(screen.getByText("canonical-master.v1")).toBeInTheDocument();
});

it("shows terminal failure and safe partial output together", async () => {
  const value = inspection();
  value.run.status = "failed";
  value.run.error_code = "RENDER_FAILED";
  stubApi(value, graph());
  renderPage();

  expect(await screen.findByText("RENDER_FAILED")).toBeInTheDocument();
  expect(screen.getByText("canonical-master.v1")).toBeInTheDocument();
});

it("does not request a Generate graph for Import runs", async () => {
  const value = inspection();
  value.run.run_type = "import";
  const fetchMock = stubApi(value, graph());
  renderPage();

  expect(await screen.findByText("Graph Timeline")).toBeInTheDocument();
  expect(screen.getByText(/Import 与 Edit Run 使用持久事件时间线/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("keeps the timeline usable when Graph evidence fails", async () => {
  stubApi(inspection(), graph(), true);
  renderPage();

  expect(await screen.findByText("Graph Timeline")).toBeInTheDocument();
  expect(await screen.findByText(/Graph 执行证据暂时不可用/)).toBeInTheDocument();
  expect(screen.getAllByTestId("inspection-event")).toHaveLength(3);
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><RunInspectorPage runId={RUN_ID} /></QueryClientProvider>);
}

function stubApi(value: RunInspectionFacts, graphValue: RunGraphReadModel, graphFails = false) {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/graph")) {
      return Promise.resolve(new Response(
        graphFails ? JSON.stringify({ error: { code: "CHECKPOINT_HISTORY_READ_FAILED", message: "unavailable" } }) : JSON.stringify({ data: graphValue }),
        { status: graphFails ? 503 : 200, headers: { "Content-Type": "application/json" } },
      ));
    }
    return Promise.resolve(new Response(JSON.stringify({ data: value }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function inspection(): RunInspectionFacts {
  return {
    run: { run_id: RUN_ID, project_id: PROJECT_ID, thread_id: "thread-1", run_type: "generate", status: "succeeded", version: 5, revision_id: REVISION_ID, bundle_id: "44444444-4444-4444-8444-444444444444", error_code: null },
    versions: { graph_topology_version: "motif-forge-parent.v2", state_schema_version: "parent-state.v2" },
    usage: { submitted_model_requests: 0, max_model_requests: 3, max_total_tokens: 12000, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, usage_status: "known", cost_status: "known", cost_amount_microusd: 0 },
    timeline: [1, 2, 3].map((sequence) => ({ sequence, event_type: sequence === 1 ? "ai_run.created" : "graph.progress", phase: sequence === 3 ? "succeeded" : "planning", created_at: `2026-08-25T00:00:0${sequence}Z`, summary: { phase: sequence === 3 ? "succeeded" : "planning" } })),
    timeline_truncated: false,
    decisions: [{ kind: "plan", decision: "approve", actor_id: "local-user", decided_at: "2026-08-25T00:00:02Z" }],
    jobs: [{ job_id: "55555555-5555-4555-8555-555555555555", job_type: "render_canonical", status: "succeeded", attempts: 1, error_code: null }],
    artifacts: [{ artifact_id: "66666666-6666-4666-8666-666666666666", source_job_id: "55555555-5555-4555-8555-555555555555", quality_profile: "canonical-master.v1", availability: "available", byte_size: 4096 }],
    recovery: { resume_events: 1, replay_events: 1, retry_events: 0, cancel_events: 0, terminal_outcome: "succeeded" },
  };
}

function graph(): RunGraphReadModel {
  return {
    schema_version: "run-graph-view.v1", run_id: RUN_ID, graph_version: "motif-forge-parent.v2",
    graph_kind: "generate", run_status: "succeeded", evidence_status: "available", current_phase_id: null,
    phases: [{ id: "planning", label: "理解与规划", status: "completed", summary: "已确认 1 个节点", node_ids: ["planning:validate-request"], collapsed_by_default: false, iteration_count: 1 }],
    nodes: [{ id: "planning:validate-request", phase_id: "planning", label: "校验生成请求", technical_name: "ValidateRequest", kind: "deterministic", evidence: "checkpoint_confirmed", status: "completed", occurred_at: null, iteration_count: 1, default_visible: true }],
    edges: [], evidence_summary: { checkpoint_count: 3, task_count: 1, event_count: 3, human_decision_count: 1, job_count: 1, unmapped_task_count: 0, truncated: false, schema_compatible: true },
  };
}
