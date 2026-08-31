import type { GraphNodeView, GraphPhaseView } from "../../shared/openapi";
import { GraphNode } from "./GraphNode";

export function GraphStageLane({
  phase,
  nodes,
  selectedId,
  onSelect,
}: {
  phase: GraphPhaseView;
  nodes: GraphNodeView[];
  selectedId: string | null;
  onSelect: (node: GraphNodeView) => void;
}) {
  const nodeList = <div
    className={`graph-stage-nodes ${phase.id === "candidates" ? "graph-parallel-group" : ""}`}
    aria-label={phase.id === "candidates" ? "并行候选分支" : undefined}
  >
    {phase.id === "candidates" && <small className="graph-group-evidence">checkpoint 分组确认</small>}
    {nodes.map((node) => <GraphNode
      key={node.id}
      node={node}
      selected={selectedId === node.id}
      onSelect={onSelect}
    />)}
  </div>;

  return <section className="graph-stage-lane" data-status={phase.status}>
    <header>
      <div><span>{String(phase.id === "error" ? "!" : phase.id).toUpperCase()}</span><h3>{phase.label}</h3></div>
      <p>{phase.summary}</p>
    </header>
    {phase.id === "export" && phase.iteration_count > 1
      ? <details className="graph-loop-group"><summary>导出管线 × {phase.iteration_count}</summary>{nodeList}</details>
      : nodeList}
  </section>;
}
