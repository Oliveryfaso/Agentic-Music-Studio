import type { RunGraphReadModel } from "../../shared/openapi";

export function ExecutionPathStrip({
  graph,
  inspectorHref,
}: {
  graph: RunGraphReadModel;
  inspectorHref?: string;
}) {
  return <section className="execution-path-strip" aria-label="Agent 执行路径">
    <div className="execution-path-heading">
      <div>
        <span className="path-kicker">LANGGRAPH SIGNAL</span>
        <strong>执行路径</strong>
      </div>
      {inspectorHref && <a href={inspectorHref}>查看完整 Graph</a>}
    </div>
    {graph.evidence_status !== "available" && <p className="graph-evidence-notice">
      {graph.evidence_status === "partial" ? "仅显示已确认的部分路径" : "Checkpoint 路径暂不可用"}
    </p>}
    <div className="execution-path-scroll">
      <ol>
        {graph.phases.filter((phase) => phase.id !== "error" || phase.status !== "not_visited").map((phase) => <li key={phase.id} data-status={phase.status}>
          <i aria-hidden="true" />
          <span data-status={phase.status}>{phase.label}</span>
          <small>{phase.summary}</small>
        </li>)}
      </ol>
    </div>
  </section>;
}
