import { useQuery } from "@tanstack/react-query";

import { StatusBanner } from "../../app/StatusBanner";
import { routePath } from "../../app/routes";
import type { RevisionExportProjection } from "../../shared/openapi";
import { readRevisionExport } from "./exportApi";

export function ExportPage({ projectId, revisionId }: { projectId: string; revisionId: string }) {
  const query = useQuery({ queryKey: ["revision-export", projectId, revisionId], queryFn: () => readRevisionExport(projectId, revisionId) });
  if (query.isPending) return <section className="loading-state"><div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div><h2>读取导出事实</h2><p>正在加载 Revision、Jobs、Artifacts 与 Bundle。</p></section>;
  if (query.isError) return <section className="error-state" role="alert"><span>!</span><div><h2>无法读取导出</h2><p>{message(query.error)}</p><button className="secondary-inline" type="button" onClick={() => void query.refetch()}>重试</button></div></section>;
  const value = query.data;
  return <section className="export-page">
    <header className="export-hero"><div><p className="eyebrow">DELIVERY / AUTHORITATIVE FACTS</p><h1>Revision Export</h1><p>只展示 PostgreSQL 与 Artifact Store 已确认的交付结果，不在页面加载时重新渲染。</p></div><div className="export-actions"><a className="secondary-inline" href={routePath({ name: "studio", projectId, revisionId })}>返回 Studio</a>{value.source_run_id && <a className="secondary-inline" href={routePath({ name: "inspect", runId: value.source_run_id })}>检查 Run</a>}</div></header>
    {value.status !== "ready" && <StatusBanner tone={value.status === "failed" ? "danger" : "warning"} message="导出部分完成" detail={`安全完成的文件仍可用；${value.error_code ?? "其余步骤尚未形成权威结果"}。`} />}
    <section className="export-panel" aria-labelledby="export-steps-title"><div className="panel-heading"><div><p className="eyebrow">SEVEN-STEP CURSOR</p><h2 id="export-steps-title">导出步骤</h2></div><span className={`status-pill ${value.status === "ready" ? "available" : "warning"}`}>{statusLabel(value.status)}</span></div><div className="export-step-scroll"><ol className="export-step-list">{value.steps.map((step) => <li data-testid="export-step" key={step.step}><span>{stepLabel(step.step)}</span><strong>{step.status}</strong>{step.error_code && <code>{step.error_code}</code>}<small>{step.job_id ?? "尚未入队"}</small></li>)}</ol></div></section>
    <section className="export-panel" aria-labelledby="export-files-title"><div className="panel-heading"><div><p className="eyebrow">FILES / LINEAGE</p><h2 id="export-files-title">交付文件</h2></div><span className="count-badge">{value.files.length}</span></div>{value.files.length === 0 ? <div className="empty-panel"><p>这个 Revision 还没有安全可下载的文件。</p></div> : <div className="export-file-grid">{value.files.map((file) => <ExportFile key={file.file_id} file={file} />)}</div>}</section>
  </section>;
}

function ExportFile({ file }: { file: RevisionExportProjection["files"][number] }) {
  const label = fileLabel(file.category, file.filename);
  return <article className="export-file-card"><div><span>{file.category}</span><h3>{label}</h3></div><dl><div><dt>格式</dt><dd>{file.media_type}</dd></div><div><dt>大小</dt><dd>{formatBytes(file.byte_size)}</dd></div><div><dt>状态</dt><dd>{file.availability}</dd></div></dl><code title={file.checksum}>{file.checksum.slice(0, 12)}…</code>{file.availability === "available" ? <a className="primary-button" href={file.content_url} download={file.filename}>{`下载 ${label}`}</a> : <p>文件当前不可下载；返回 Studio 可恢复受支持的音频 Artifact。</p>}</article>;
}

function fileLabel(category: string, filename: string): string { if (category === "master") return "Master WAV"; if (category === "delivery") return "Delivery MP3"; if (category === "stem") return `Stem · ${filename}`; if (category === "midi") return "Composition MIDI"; if (category === "project") return "Canonical Project"; return filename; }
function stepLabel(step: string): string { return step.replace("stem:", "Stem · ").replace("mp3", "Delivery MP3").replace("bundle", "Bundle"); }
function statusLabel(status: string): string { return status === "ready" ? "完整可交付" : status === "failed" ? "部分失败" : "进行中"; }
function formatBytes(value: number): string { return value < 1024 ? `${value} B` : value < 1024 ** 2 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1024 ** 2).toFixed(1)} MiB`; }
function message(error: unknown): string { return error instanceof Error ? error.message : "客户端发生未知错误"; }
