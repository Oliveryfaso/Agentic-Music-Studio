import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import type { RunGraphReadModel } from "../../shared/openapi";
import { ExecutionPathStrip } from "./ExecutionPathStrip";

afterEach(cleanup);

it("summarizes completed, waiting, and next phases without pretending evidence", () => {
  render(<ExecutionPathStrip graph={graph()} inspectorHref="/runs/1/inspect" />);

  expect(screen.getByLabelText("Agent 执行路径")).toBeInTheDocument();
  expect(screen.getByText("理解与规划")).toHaveAttribute("data-status", "completed");
  expect(screen.getByText("选择与落版")).toHaveAttribute("data-status", "waiting");
  expect(screen.getByText("完整导出")).toHaveAttribute("data-status", "not_visited");
  expect(screen.getByRole("link", { name: "查看完整 Graph" })).toHaveAttribute(
    "href",
    "/runs/1/inspect",
  );
});

it("states partial and unavailable evidence explicitly", () => {
  const partial = graph();
  partial.evidence_status = "partial";
  const { rerender } = render(<ExecutionPathStrip graph={partial} />);
  expect(screen.getByText("仅显示已确认的部分路径")).toBeInTheDocument();

  partial.evidence_status = "unavailable";
  rerender(<ExecutionPathStrip graph={partial} />);
  expect(screen.getByText("Checkpoint 路径暂不可用")).toBeInTheDocument();
});

function graph(): RunGraphReadModel {
  return {
    schema_version: "run-graph-view.v1",
    run_id: "11111111-1111-4111-8111-111111111111",
    graph_version: "motif-forge-parent.v2",
    graph_kind: "generate",
    run_status: "waiting_worker",
    evidence_status: "available",
    current_phase_id: "commit",
    phases: [
      { id: "planning", label: "理解与规划", status: "completed", summary: "已确认 5 个节点", node_ids: [], collapsed_by_default: false, iteration_count: 1 },
      { id: "approval", label: "计划确认", status: "completed", summary: "已确认 1 个节点", node_ids: [], collapsed_by_default: false, iteration_count: 1 },
      { id: "commit", label: "选择与落版", status: "waiting", summary: "等待人工决定", node_ids: [], collapsed_by_default: false, iteration_count: 0 },
      { id: "export", label: "完整导出", status: "not_visited", summary: "尚未访问", node_ids: [], collapsed_by_default: false, iteration_count: 0 },
    ],
    nodes: [],
    edges: [],
    evidence_summary: { checkpoint_count: 12, task_count: 8, event_count: 3, human_decision_count: 1, job_count: 2, unmapped_task_count: 0, truncated: false, schema_compatible: true },
  };
}
