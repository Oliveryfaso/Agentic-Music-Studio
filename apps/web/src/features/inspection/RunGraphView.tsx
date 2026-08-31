import { useMemo, useState } from "react";

import type { GraphNodeView, RunGraphReadModel } from "../../shared/openapi";
import { GraphEvidencePanel } from "./GraphEvidencePanel";
import { GraphStageLane } from "./GraphStageLane";

export function RunGraphView({ graph }: { graph: RunGraphReadModel }) {
  const [showTechnical, setShowTechnical] = useState(false);
  const [selected, setSelected] = useState<GraphNodeView | null>(null);
  const visibleNodes = useMemo(
    () => graph.nodes.filter((node) => (
      showTechnical
      || node.default_visible
      || (node.phase_id === "error" && node.status !== "not_visited")
    )),
    [graph.nodes, showTechnical],
  );

  return <section
    className="run-graph-view motion-safe-signal"
    aria-label="Generate Parent Graph 执行路径"
  >
    <header className="run-graph-toolbar">
      <div>
        <span className="path-kicker">{graph.graph_version}</span>
        <h2>Signal Path Graph</h2>
        <p>形状表示责任，颜色表示执行类型；只有持久证据会点亮节点。</p>
      </div>
      <button className="secondary-inline" type="button" onClick={() => setShowTechnical((value) => !value)}>
        {showTechnical ? "隐藏技术节点" : "显示技术节点"}
      </button>
    </header>
    {graph.evidence_status !== "available" && <p className="graph-read-status" role="status">
      {graph.evidence_status === "partial" ? "部分 checkpoint 证据：未确认路径保持熄灭。" : "Checkpoint 执行证据不可用；请使用下方持久事件时间线。"}
    </p>}
    <div className="run-graph-layout">
      <div className="graph-stage-list">
        {graph.phases.filter((phase) => phase.id !== "error" || phase.status !== "not_visited").map((phase) => <GraphStageLane
          key={phase.id}
          phase={phase}
          nodes={visibleNodes.filter((node) => node.phase_id === phase.id)}
          selectedId={selected?.id ?? null}
          onSelect={setSelected}
        />)}
      </div>
      <GraphEvidencePanel node={selected} />
    </div>
  </section>;
}
