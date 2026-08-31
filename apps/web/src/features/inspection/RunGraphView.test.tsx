import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import type { RunGraphReadModel } from "../../shared/openapi";
import { RunGraphView } from "./RunGraphView";

afterEach(cleanup);

it("renders a natural signal path with exact technical evidence and parallel candidates", () => {
  render(<RunGraphView graph={graph()} />);

  const view = screen.getByLabelText("Generate Parent Graph 执行路径");
  expect(view).toHaveClass("run-graph-view");
  expect(screen.getByText("生成候选 A")).toBeInTheDocument();
  expect(screen.getByText("生成候选 B")).toBeInTheDocument();
  expect(screen.getAllByText("CreateCandidateBranch")).toHaveLength(2);
  expect(screen.getByLabelText("并行候选分支")).toBeInTheDocument();
  expect(screen.getByText("checkpoint 分组确认")).toBeInTheDocument();

  const candidate = screen.getByRole("button", { name: /生成候选 A/ });
  fireEvent.click(candidate);
  const evidence = screen.getByRole("region", { name: "节点证据" });
  expect(within(evidence).getByText("CreateCandidateBranch")).toBeInTheDocument();
  expect(within(evidence).getByText("执行 1 次")).toBeInTheDocument();
});

it("collapses repeated export evidence and reveals default-hidden technical nodes", () => {
  render(<RunGraphView graph={graph()} />);

  expect(screen.getByText("导出管线 × 7")).toBeInTheDocument();
  expect(screen.queryByText("准备规划输入")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "显示技术节点" }));
  expect(screen.getByText("准备规划输入")).toBeInTheDocument();
});

it("keeps failed, partial, and reduced-motion semantics in text", () => {
  const value = graph();
  value.evidence_status = "partial";
  value.nodes[0]!.status = "failed";
  render(<RunGraphView graph={value} />);

  expect(screen.getByRole("status")).toHaveTextContent("部分 checkpoint 证据");
  expect(screen.getByRole("button", { name: /校验生成请求/ })).toHaveAttribute(
    "data-status",
    "failed",
  );
  expect(screen.getByLabelText("Generate Parent Graph 执行路径")).toHaveClass(
    "motion-safe-signal",
  );
});

function graph(): RunGraphReadModel {
  return {
    schema_version: "run-graph-view.v1",
    run_id: "11111111-1111-4111-8111-111111111111",
    graph_version: "motif-forge-parent.v2",
    graph_kind: "generate",
    run_status: "succeeded",
    evidence_status: "available",
    current_phase_id: null,
    phases: [
      { id: "planning", label: "理解与规划", status: "completed", summary: "已确认 3 个节点", node_ids: ["planning:validate-request", "planning:input-adapter"], collapsed_by_default: false, iteration_count: 1 },
      { id: "candidates", label: "候选生成", status: "completed", summary: "已确认 3 个节点", node_ids: ["candidates:candidate-a", "candidates:candidate-b", "candidates:fan-in"], collapsed_by_default: false, iteration_count: 1 },
      { id: "export", label: "完整导出", status: "completed", summary: "已确认 3 个节点 (重复 7 次)", node_ids: ["export:enqueue", "export:wait", "export:complete"], collapsed_by_default: false, iteration_count: 7 },
    ],
    nodes: [
      node("planning:validate-request", "planning", "校验生成请求", "ValidateRequest", "deterministic", "checkpoint_confirmed", "completed", 1),
      { ...node("planning:input-adapter", "planning", "准备规划输入", "PlanInputAdapter", "deterministic", "checkpoint_confirmed", "completed", 1), default_visible: false },
      node("candidates:candidate-a", "candidates", "生成候选 A", "CreateCandidateBranch", "deterministic", "grouped_parallel", "completed", 1),
      node("candidates:candidate-b", "candidates", "生成候选 B", "CreateCandidateBranch", "deterministic", "grouped_parallel", "completed", 1),
      node("candidates:fan-in", "candidates", "汇合候选", "CandidateFanIn", "deterministic", "checkpoint_confirmed", "completed", 1),
      node("export:enqueue", "export", "推进完整导出", "EnqueueCompleteExportStep", "worker", "checkpoint_confirmed", "completed", 7),
      node("export:wait", "export", "等待导出任务", "WaitForGenerateJobEvent", "worker", "checkpoint_confirmed", "completed", 7),
      node("export:complete", "export", "完成整曲生成", "CompleteGenerate", "deterministic", "checkpoint_confirmed", "completed", 1),
    ],
    edges: [
      { source: "candidates:candidate-a", target: "candidates:fan-in", relation: "join", status: "traversed" },
      { source: "candidates:candidate-b", target: "candidates:fan-in", relation: "join", status: "traversed" },
      { source: "export:enqueue", target: "export:wait", relation: "worker_boundary", status: "traversed" },
      { source: "export:wait", target: "export:enqueue", relation: "loop", status: "traversed" },
    ],
    evidence_summary: { checkpoint_count: 44, task_count: 28, event_count: 10, human_decision_count: 2, job_count: 7, unmapped_task_count: 0, truncated: false, schema_compatible: true },
  };
}

function node(
  id: string,
  phase_id: string,
  label: string,
  technical_name: string,
  kind: "deterministic" | "agent" | "human" | "worker",
  evidence: "checkpoint_confirmed" | "event_confirmed" | "grouped_parallel" | "none",
  status: "completed" | "active" | "waiting" | "failed" | "skipped" | "not_visited",
  iteration_count: number,
) {
  return { id, phase_id, label, technical_name, kind, evidence, status, occurred_at: null, iteration_count, default_visible: true };
}
