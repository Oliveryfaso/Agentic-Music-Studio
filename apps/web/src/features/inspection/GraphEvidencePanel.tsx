import type { GraphNodeView } from "../../shared/openapi";
import { evidenceLabel } from "./GraphNode";

export function GraphEvidencePanel({ node }: { node: GraphNodeView | null }) {
  return <section className="graph-evidence-panel" role="region" aria-label="节点证据">
    {node ? <>
      <div>
        <span className="path-kicker">SELECTED NODE</span>
        <h3>{node.label}</h3>
      </div>
      <dl>
        <div><dt>技术节点</dt><dd><code>{node.technical_name}</code></dd></div>
        <div><dt>证据</dt><dd>{evidenceLabel(node.evidence)}</dd></div>
        <div><dt>状态</dt><dd>{node.status}</dd></div>
        <div><dt>重复</dt><dd>执行 {node.iteration_count} 次</dd></div>
        <div><dt>应用事件时间</dt><dd>{node.occurred_at ? new Date(node.occurred_at).toLocaleString("zh-CN", { hour12: false }) : "checkpoint 未保存时间戳"}</dd></div>
      </dl>
    </> : <div className="graph-evidence-empty"><span className="path-kicker">NODE EVIDENCE</span><p>选择一个节点查看受限证据。不会显示 Prompt、模型推理或 checkpoint payload。</p></div>}
  </section>;
}
