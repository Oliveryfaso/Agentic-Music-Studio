import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { StatusBanner } from "../../app/StatusBanner";
import { useLocationSearch } from "../../app/NavigationGuard";
import { navigateHref, routePath } from "../../app/routes";
import type { RevisionExportProjection } from "../../shared/openapi";
import { readRevisionExport, startRevisionExport, cancelRevisionExport } from "./exportApi";

export function ExportPage({ projectId, revisionId }: { projectId: string; revisionId: string }) {
  const queryPlan=new URLSearchParams(useLocationSearch()).get("export_plan") ?? undefined;
  const planHash = queryPlan;
  const lifetime = useRef({ active: false, pathname: window.location.pathname });
  useEffect(() => { const page = lifetime.current; page.active = true; return () => { page.active = false; }; }, []);
  const ownsPlan = () => lifetime.current.active && window.location.pathname === lifetime.current.pathname
    && (new URLSearchParams(window.location.search).get("export_plan") ?? undefined) === planHash;
  const [includeMp3, setIncludeMp3] = useState(true);
  const [allStems, setAllStems] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const request = useRef<{ key: string; body: string } | null>(null);
  const operation = useRef(0);
  useEffect(() => {
    ++operation.current;
    setBusy(false); setActionError(null); request.current = null;
  }, [planHash]);
  const query = useQuery({ queryKey: ["revision-export", projectId, revisionId, planHash],
    queryFn: () => readRevisionExport(projectId, revisionId, planHash),
    refetchInterval: (q) => q.state.data?.export_thread_id && q.state.data.status === "partial" ? 2000 : false });
  const matchesPlan = !planHash || query.data?.plan_hash === planHash;
  async function start(retryRequest = false) {
    if (busy || !ownsPlan() || !matchesPlan) return;
    const token = ++operation.current;
    const ownsRequest = () => ownsPlan() && operation.current === token;
    setBusy(true); setActionError(null);
    const options = { include_mp3: includeMp3, include_all_stems: allStems };
    const body = JSON.stringify(options);
    if (!retryRequest || request.current?.body !== body) request.current = { key: crypto.randomUUID(), body };
    const pending = request.current!;
    try {
      const result = await startRevisionExport(projectId, revisionId, options, pending.key);
      if (!result.plan_hash) throw new Error("导出未返回文件计划，请重试请求。");
      if (!ownsRequest()) return;
      const url = new URL(window.location.href); url.searchParams.set("export_plan", result.plan_hash);
      request.current = null;
      setBusy(false);
      navigateHref(url.href, true);
    } catch (error) { if (ownsRequest()) setActionError(message(error)); }
    finally { if (ownsRequest()) setBusy(false); }
  }
  async function cancel(threadId: string) {
    if (busy || !ownsPlan() || !matchesPlan || query.data?.export_thread_id !== threadId) return;
    const token = ++operation.current;
    const ownsRequest = () => ownsPlan() && operation.current === token;
    setBusy(true); setActionError(null);
    try { await cancelRevisionExport(projectId, revisionId, threadId); if (ownsRequest()) await query.refetch(); }
    catch (error) { if (ownsRequest()) setActionError(message(error)); }
    finally { if (ownsRequest()) setBusy(false); }
  }
  if (query.isPending) return <section className="loading-state"><div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div><h2>正在整理交付文件</h2><p>读取当前版本已完成的音频与工程文件。</p></section>;
  if (query.isError) return <section className="error-state" role="alert"><span>!</span><div><h2>无法读取导出</h2><p>{message(query.error)}</p><button className="secondary-inline" type="button" onClick={() => void query.refetch()}>重试</button></div></section>;
  const value = query.data;
  if (!matchesPlan) return <section className="export-page" aria-live="polite"><StatusBanner tone="warning" message="导出计划未确认" detail="重新读取当前链接的计划。" /><div className="export-actions"><button className="secondary-inline" type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>重新读取导出</button><a className="secondary-inline" href={routePath({ name: "studio", projectId, revisionId })}>返回 Studio</a></div></section>;
  const notStarted=value.status==="partial"&&!value.export_thread_id&&!value.plan_hash&&!value.bundle&&!value.error_code&&value.files.length===0&&value.steps.every(step=>!step.job_id&&step.status==="pending");
  return <section className="export-page">
    <header className="export-hero"><div><a className="workspace-back" href="/">作品 / 导出</a><h1>导出</h1><p>保存版 {revisionId.slice(0,8)}</p></div><div className="export-actions"><span className="status-pill">{notStarted?"尚未生成导出":statusLabel(value.status)}</span><a className="secondary-inline" href={routePath({ name: "studio", projectId, revisionId })}>返回 Studio</a>{value.source_run_id && <a className="secondary-inline" href={routePath({ name: "inspect", runId: value.source_run_id })}>查看执行记录</a>}</div></header>
    <section className="export-panel" aria-label="导出选项"><div className="export-actions">
      <label><input type="checkbox" checked={includeMp3} onChange={(event) => setIncludeMp3(event.target.checked)} disabled={busy} />包含试听 MP3</label>
      <label><input type="checkbox" checked={allStems} onChange={(event) => setAllStems(event.target.checked)} disabled={busy} />包含独立分轨</label>
      <button className="primary-button" type="button" disabled={busy || (Boolean(value.export_thread_id) && value.status === "partial")} onClick={() => void start()}>{value.files.length ? "重新导出" : "生成导出文件"}</button>
      {value.export_thread_id && value.status === "partial" && <button className="secondary-inline" type="button" disabled={busy} onClick={() => void cancel(value.export_thread_id!)}>取消导出</button>}
    </div><p>Master WAV、MIDI 和工程文件始终包含；分轨按当前版本的实际音轨生成。</p>
    {actionError && <div role="alert"><p>{actionError}</p>{request.current && <button type="button" disabled={busy} onClick={() => void start(true)}>重试请求</button>}</div>}</section>
    {notStarted ? <StatusBanner message="编排已保存，导出文件尚未生成" detail="选择导出选项后，点击“生成导出文件”。打开此页不会自动开始渲染。" /> : value.status === "cancelled" ? <StatusBanner tone="warning" message="导出已取消" detail="已完成的文件仍可下载。可以重新生成一份导出。" /> : value.status !== "ready" && <StatusBanner tone={value.status === "failed" ? "danger" : "warning"} message="导出部分完成" detail={`已完成的文件仍可下载；${value.error_code ?? "其余文件尚未就绪"}。`} />}
    <section className="export-panel" aria-labelledby="export-files-title"><div className="panel-heading"><div><h2 id="export-files-title">交付文件</h2></div><span className="count-badge">{value.files.length}</span></div>{value.files.length === 0 ? <div className="empty-panel"><p>{notStarted?"先生成导出文件，再下载 WAV、MIDI 和工程。":"当前版本还没有可下载文件。请查看任务进度，完成后刷新此页。"}</p></div> : <div className="export-file-grid" role="list" aria-label="导出文件">{value.files.map((file) => <ExportFile key={file.file_id} file={file} />)}</div>}</section>
    <details className="export-panel export-steps-details" open={!notStarted&&value.status !== "ready"}><summary>查看导出步骤与任务状态 · {value.steps.filter((step) => step.status === "succeeded").length}/{value.steps.length} 完成</summary><div className="export-step-scroll"><ol className="export-step-list">{value.steps.map((step) => <li data-testid="export-step" key={step.step}><span>{stepLabel(step.step)}</span><strong>{jobLabel(step.status)}</strong>{step.error_code && <code>{step.error_code}</code>}<small>{step.job_id ?? "尚未入队"}</small></li>)}</ol></div></details>
  </section>;
}

function ExportFile({ file }: { file: RevisionExportProjection["files"][number] }) {
  const label = fileLabel(file.category, file.filename);
  return <article className="export-file-card" role="listitem"><div><span>{file.category}</span><h3>{label}</h3></div><dl><div><dt>格式</dt><dd>{file.media_type}</dd></div><div><dt>大小</dt><dd>{formatBytes(file.byte_size)}</dd></div><div><dt>状态</dt><dd>{availabilityLabel(file.availability)}</dd></div></dl><details className="export-file-details"><summary>文件信息</summary><p>{file.filename}</p><code>校验标识：{file.checksum}</code></details>{file.availability === "available" ? <a className="primary-button" href={file.content_url} download={file.filename}>{`下载 ${label}`}</a> : <p>文件暂不可下载。返回 Studio 可以恢复受支持的音频文件。</p>}</article>;
}

function fileLabel(category: string, filename: string): string { if (category === "master") return "Master WAV"; if (category === "delivery") return "试听 MP3"; if (category === "stem") return `分轨 · ${filename}`; if (category === "midi") return "乐谱 MIDI"; if (category === "project") return "可编辑工程"; return filename; }
function stepLabel(step: string): string { return step.replace("stem:", "Stem · ").replace("mp3", "Delivery MP3").replace("bundle", "Bundle"); }
function statusLabel(status: string): string { return status === "cancelled" ? "已取消" : status === "ready" ? "文件已就绪" : status === "failed" ? "部分失败" : "进行中"; }
function formatBytes(value: number): string { return value < 1024 ? `${value} B` : value < 1024 ** 2 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1024 ** 2).toFixed(1)} MiB`; }
function message(error: unknown): string { return error instanceof Error ? error.message : "客户端发生未知错误"; }
function availabilityLabel(value: string): string { return ({ available: "可下载", evicted: "已回收，可恢复", rehydrating: "正在恢复", missing: "文件缺失" } as Record<string, string>)[value] ?? value; }
function jobLabel(value: string): string { return ({ succeeded: "已完成", queued: "排队中", running: "处理中", failed: "未完成", cancelled: "已取消", pending: "待处理" } as Record<string, string>)[value] ?? value; }
