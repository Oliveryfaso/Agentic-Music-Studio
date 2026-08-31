import { useQuery } from "@tanstack/react-query";

import { StatusBanner } from "../../app/StatusBanner";
import { routePath } from "../../app/routes";
import { readRunGraph, readRunInspection } from "./inspectionApi";
import { RunGraphView } from "./RunGraphView";

export function RunInspectorPage({ runId }: { runId: string }) {
  const query = useQuery({ queryKey: ["run-inspection", runId], queryFn: () => readRunInspection(runId) });
  const graphQuery = useQuery({
    queryKey: ["run-graph", runId],
    queryFn: () => readRunGraph(runId),
    enabled: query.data?.run.run_type === "generate",
  });
  if (query.isPending) return <section className="loading-state"><div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div><h2>恢复 Run 证据</h2><p>正在读取持久事件、决策、预算和输出 lineage。</p></section>;
  if (query.isError) return <section className="error-state" role="alert"><span>!</span><div><h2>无法读取 Run Inspector</h2><p>{message(query.error)}</p><button className="secondary-inline" type="button" onClick={() => void query.refetch()}>重试</button></div></section>;
  const value = query.data;
  return <section className="inspection-page">
    <header className="inspection-hero"><div><p className="eyebrow">PARENT GRAPH / READ-ONLY EVIDENCE</p><h1>Run Inspector</h1><p>从持久事实解释这次 Agent 运行发生了什么；不显示 Prompt、审批断言或本地路径。</p></div><div className="inspection-links"><a className="secondary-inline" href={routePath({ name: "run", runId })}>返回 Run</a>{value.run.revision_id && <><a className="secondary-inline" href={routePath({ name: "studio", projectId: value.run.project_id, revisionId: value.run.revision_id })}>打开 Studio</a><a className="secondary-inline" href={routePath({ name: "export", projectId: value.run.project_id, revisionId: value.run.revision_id })}>查看导出</a></>}</div></header>
    {value.run.error_code && <StatusBanner tone="danger" message="Run 以明确错误结束" detail={value.run.error_code} />}
    <section className="inspection-fact-grid" aria-label="Run 概览">
      <article><span>状态</span><strong>{value.run.status}</strong><small>v{value.run.version} · {value.run.run_type}</small></article>
      <article><span>Graph</span><strong>{value.versions.graph_topology_version}</strong><small>{value.versions.state_schema_version}</small></article>
      <article><span>预算</span><strong>{value.usage.submitted_model_requests} / {value.usage.max_model_requests} model requests</strong><small>{value.usage.total_tokens ?? "unknown"} / {value.usage.max_total_tokens} tokens</small></article>
      <article><span>恢复</span><strong>{value.recovery.resume_events} resume · {value.recovery.replay_events} replay</strong><small>{value.recovery.terminal_outcome ?? "nonterminal"}</small></article>
    </section>
    {value.run.run_type === "generate"
      ? graphQuery.isPending
        ? <p className="graph-read-status" role="status">正在读取 checkpoint 执行证据…</p>
        : graphQuery.isError
          ? <StatusBanner tone="warning" message="Graph 执行证据暂时不可用" detail="下方持久事件时间线仍可用于检查这次运行。" />
          : <RunGraphView graph={graphQuery.data} />
      : <StatusBanner tone="info" message="此 Run 不使用 Generate Graph 视图" detail="Import 与 Edit Run 使用持久事件时间线。" />}
    <div className="inspection-columns">
      <section className="inspection-panel"><div className="panel-heading"><h2>Human Decisions</h2><span className="count-badge">{value.decisions.length}</span></div>{value.decisions.length ? <ul className="inspection-list">{value.decisions.map((decision) => <li key={`${decision.kind}:${decision.decided_at}`}><strong>{kindLabel(decision.kind)} · {decision.decision}</strong><span>{decision.actor_id}</span><small>{formatTime(decision.decided_at)}</small></li>)}</ul> : <div className="empty-panel"><p>没有持久化人工决策。</p></div>}</section>
      <section className="inspection-panel"><div className="panel-heading"><h2>Usage & Cost</h2></div><dl className="inspection-usage"><div><dt>Prompt</dt><dd>{value.usage.prompt_tokens ?? "unknown"}</dd></div><div><dt>Completion</dt><dd>{value.usage.completion_tokens ?? "unknown"}</dd></div><div><dt>Usage</dt><dd>{value.usage.usage_status}</dd></div><div><dt>Cost</dt><dd>{formatCost(value.usage.cost_amount_microusd, value.usage.cost_status)}</dd></div></dl></section>
    </div>
    <section className="inspection-panel"><div className="panel-heading"><div><p className="eyebrow">AUTHORITATIVE OUTPUTS</p><h2>Jobs & Artifacts</h2></div><span className="count-badge">{value.jobs.length} / {value.artifacts.length}</span></div><div className="inspection-output-grid"><div><h3>Jobs</h3><ul className="inspection-list">{value.jobs.map((job) => <li key={job.job_id}><strong>{job.job_type}</strong><span>{job.status} · attempt {job.attempts}</span>{job.error_code && <small>{job.error_code}</small>}</li>)}</ul></div><div><h3>Artifacts</h3><ul className="inspection-list">{value.artifacts.map((artifact) => <li key={artifact.artifact_id}><strong>{artifact.quality_profile}</strong><span>{artifact.availability} · {formatBytes(artifact.byte_size)}</span><small>{artifact.artifact_id}</small></li>)}</ul></div></div></section>
    <details className="inspection-panel inspection-timeline-details"><summary><span><span className="eyebrow">PERSISTED EVENT ORDER</span><strong>Graph Timeline</strong></span><span className="count-badge">{value.timeline.length}</span></summary>{value.timeline_truncated && <StatusBanner tone="warning" message="时间线已截断" detail="只显示最近 200 条持久事件。" />}<div className="inspection-table-scroll"><table><thead><tr><th>Seq</th><th>Phase</th><th>Event</th><th>Safe summary</th><th>Time</th></tr></thead><tbody>{value.timeline.map((event) => <tr data-testid="inspection-event" data-sequence={event.sequence} key={event.sequence}><td>{event.sequence}</td><td>{event.phase}</td><td>{event.event_type}</td><td><code>{formatSummary(event.summary)}</code></td><td>{formatTime(event.created_at)}</td></tr>)}</tbody></table></div></details>
  </section>;
}

function formatSummary(summary: Record<string, string | number | boolean | null>): string { return Object.entries(summary).map(([key, value]) => `${key}=${String(value)}`).join(" · ") || "—"; }
function kindLabel(kind: string): string { return kind === "plan" ? "Plan" : "Edit"; }
function formatTime(value: string): string { return new Date(value).toLocaleString("zh-CN", { hour12: false }); }
function formatBytes(value: number): string { return value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KiB`; }
function formatCost(value: number | null | undefined, status: string): string { return value == null ? status : `$${(value / 1_000_000).toFixed(6)} · ${status}`; }
function message(error: unknown): string { return error instanceof Error ? error.message : "客户端发生未知错误"; }
