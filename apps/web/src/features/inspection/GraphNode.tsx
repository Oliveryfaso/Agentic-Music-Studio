import type { GraphNodeView } from "../../shared/openapi";

const STATUS_LABELS: Record<GraphNodeView["status"], string> = {
  completed: "已完成",
  active: "执行中",
  waiting: "等待人工决定",
  failed: "失败",
  skipped: "已跳过",
  not_visited: "尚未访问",
};

const KIND_LABELS: Record<GraphNodeView["kind"], string> = {
  deterministic: "确定性代码",
  agent: "Agent / 模型",
  human: "人工决策",
  worker: "异步 Worker",
};

export function GraphNode({
  node,
  selected,
  onSelect,
}: {
  node: GraphNodeView;
  selected: boolean;
  onSelect: (node: GraphNodeView) => void;
}) {
  return <button
    className={`graph-node graph-node-${node.kind}`}
    type="button"
    data-status={node.status}
    data-evidence={node.evidence}
    aria-pressed={selected}
    aria-label={`${node.label}，${STATUS_LABELS[node.status]}，${KIND_LABELS[node.kind]}`}
    onClick={() => onSelect(node)}
  >
    <span className="graph-node-shape" aria-hidden="true" />
    <span className="graph-node-copy">
      <strong>{node.label}</strong>
      <code>{node.technical_name}</code>
      <small>{STATUS_LABELS[node.status]} · {KIND_LABELS[node.kind]}</small>
    </span>
  </button>;
}
export function evidenceLabel(value: GraphNodeView["evidence"]): string {
  if (value === "checkpoint_confirmed") return "checkpoint 确认";
  if (value === "event_confirmed") return "应用事件确认";
  if (value === "grouped_parallel") return "checkpoint 分组确认";
  return "没有执行证据";
}
