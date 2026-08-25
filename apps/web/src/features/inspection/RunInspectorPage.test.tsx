import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { RunInspectionFacts } from "../../shared/openapi";
import { RunInspectorPage } from "./RunInspectorPage";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const REVISION_ID = "33333333-3333-4333-8333-333333333333";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows graph versions, budgets, decisions, outputs, and ordered events", async () => {
  stubInspection(inspection());
  renderPage();

  expect(await screen.findByText("motif-forge-parent.v2")).toBeInTheDocument();
  expect(screen.getByText("0 / 3 model requests")).toBeInTheDocument();
  expect(screen.getAllByTestId("inspection-event").map((node) => node.dataset.sequence)).toEqual(["1", "2", "3"]);
  expect(screen.getByText("Plan · approve")).toBeInTheDocument();
  expect(screen.getByText("canonical-master.v1")).toBeInTheDocument();
});

it("shows terminal failure and safe partial output together", async () => {
  const value = inspection();
  value.run.status = "failed";
  value.run.error_code = "RENDER_FAILED";
  stubInspection(value);
  renderPage();

  expect(await screen.findByText("RENDER_FAILED")).toBeInTheDocument();
  expect(screen.getByText("canonical-master.v1")).toBeInTheDocument();
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><RunInspectorPage runId={RUN_ID} /></QueryClientProvider>);
}

function stubInspection(value: RunInspectionFacts) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: value }), {
    status: 200, headers: { "Content-Type": "application/json" },
  })));
}

function inspection(): RunInspectionFacts {
  return {
    run: { run_id: RUN_ID, project_id: PROJECT_ID, run_type: "generate", status: "succeeded", version: 5, revision_id: REVISION_ID, bundle_id: "44444444-4444-4444-8444-444444444444", error_code: null },
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
