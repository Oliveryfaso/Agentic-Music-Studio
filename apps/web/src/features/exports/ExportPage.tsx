import { useQuery } from "@tanstack/react-query";

import { StatusBanner } from "../../app/StatusBanner";
import { routePath } from "../../app/routes";
import type { RevisionExportProjection } from "../../shared/openapi";
import { readRevisionExport } from "./exportApi";

export function ExportPage({ projectId, revisionId }: { projectId: string; revisionId: string }) {
  const query = useQuery({ queryKey: ["revision-export", projectId, revisionId], queryFn: () => readRevisionExport(projectId, revisionId) });
  if (query.isPending) return <section className="loading-state"><div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div><h2>正在整理交付文件</h2><p>读取当前版本已完成的音频与工程文件。</p></section>;
  if (query.isError) return <section className="error-state" role="alert"><span>!</span><div><h2>无法读取导出</h2><p>{message(query.error)}</p><button className="secondary-inline" type="button" onClick={() => void query.refetch()}>重试</button></div></section>;
  const value = query.data;
  return <section className="export-page">
    <header className="export-hero"><div><p className="eyebrow">TAKE YOUR MUSIC WITH YOU</p><h1>带走你的作品</h1><p>试听分享用 MP3，后期制作用 WAV 与分轨；MIDI 和工程文件让创作可以继续。</p></div><div className="export-actions"><span className="status-pill">{statusLabel(value.status)}</span><a className="secondary-inline" href={routePath({ name: "studio", projectId, revisionId })}>返回 Studio</a>{value.source_run_id && <a className="secondary-inline" href={routePath({ name: "inspect", runId: value.source_run_id })}>查看执行记录</a>}</div></header>
    {value.status !== "ready" && <StatusBanner tone={value.status === "failed" ? "danger" : "warning"} message="导出部分完成" detail={`已完成的文件仍可下载；${value.error_code ?? "其余文件尚未就绪"}。`} />}
    <section className="export-panel" aria-labelledby="export-files-title"><div className="panel-heading"><div><p className="eyebrow">YOUR FILES</p><h2 id="export-files-title">交付文件</h2></div><span className="count-badge">{value.files.length}</span></div>{value.files.length === 0 ? <div className="empty-panel"><p>当前版本还没有可下载文件。请查看任务进度，完成后刷新此页。</p></div> : <div className="export-file-grid">{value.files.map((file) => <ExportFile key={file.file_id} file={file} />)}</div>}</section>
    <details className="export-panel export-steps-details" open={value.status !== "ready"}><summary>查看导出步骤与任务状态 · {value.steps.filter((step) => step.status === "succeeded").length}/{value.steps.length} 完成</summary><div className="export-step-scroll"><ol className="export-step-list">{value.steps.map((step) => <li data-testid="export-step" key={step.step}><span>{stepLabel(step.step)}</span><strong>{jobLabel(step.status)}</strong>{step.error_code && <code>{step.error_code}</code>}<small>{step.job_id ?? "尚未入队"}</small></li>)}</ol></div></details>
  </section>;
}

function ExportFile({ file }: { file: RevisionExportProjection["files"][number] }) {
  const label = fileLabel(file.category, file.filename);
  return <article className="export-file-card"><div><span>{file.category}</span><h3>{label}</h3><p>{fileDescription(file.category)}</p></div><dl><div><dt>格式</dt><dd>{file.media_type}</dd></div><div><dt>大小</dt><dd>{formatBytes(file.byte_size)}</dd></div><div><dt>状态</dt><dd>{availabilityLabel(file.availability)}</dd></div></dl><details className="export-file-details"><summary>文件信息</summary><p>{file.filename}</p><code>校验标识：{file.checksum}</code></details>{file.availability === "available" ? <a className="primary-button" href={file.content_url} download={file.filename}>{`下载 ${label}`}</a> : <p>文件暂不可下载。返回 Studio 可以恢复受支持的音频文件。</p>}</article>;
}

function fileLabel(category: string, filename: string): string { if (category === "master") return "Master WAV"; if (category === "delivery") return "试听 MP3"; if (category === "stem") return `分轨 · ${filename}`; if (category === "midi") return "乐谱 MIDI"; if (category === "project") return "可编辑工程"; return filename; }
function stepLabel(step: string): string { return step.replace("stem:", "Stem · ").replace("mp3", "Delivery MP3").replace("bundle", "Bundle"); }
function statusLabel(status: string): string { return status === "ready" ? "文件已就绪" : status === "failed" ? "部分失败" : "进行中"; }
function formatBytes(value: number): string { return value < 1024 ? `${value} B` : value < 1024 ** 2 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1024 ** 2).toFixed(1)} MiB`; }
function message(error: unknown): string { return error instanceof Error ? error.message : "客户端发生未知错误"; }
function fileDescription(category: string): string { return ({ master: "无损主混音，适合归档和后期制作。", delivery: "轻量压缩音频，适合试听与分享。", stem: "独立音轨，可在其他 DAW 中继续混音。", midi: "保留音符信息，方便重新配器。", project: "保留编排结构，供后续编辑与复现。" } as Record<string, string>)[category] ?? "作品随附的来源、许可或执行记录。"; }
function availabilityLabel(value: string): string { return ({ available: "可下载", evicted: "已回收，可恢复", rehydrating: "正在恢复", missing: "文件缺失" } as Record<string, string>)[value] ?? value; }
function jobLabel(value: string): string { return ({ succeeded: "已完成", queued: "排队中", running: "处理中", failed: "未完成", cancelled: "已取消", pending: "待处理" } as Record<string, string>)[value] ?? value; }
