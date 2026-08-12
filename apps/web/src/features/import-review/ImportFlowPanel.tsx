import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";

import {
  ApiError,
  audioContentUrl,
  confirmImportAnalysis,
  ConfirmImportAnalysisRequest,
  ImportRunData,
  readImportRun,
  RightsDeclaration,
  UploadProgress,
  uploadAndStartImport,
} from "../../shared/api";

const RIGHTS_OPTIONS: ReadonlyArray<{ value: RightsDeclaration; label: string }> = [
  { value: "user_owned", label: "我拥有这段音频的权利" },
  { value: "licensed", label: "已获得使用许可" },
  { value: "public_domain", label: "公共领域作品与录音" },
  { value: "cc0", label: "CC0" },
  { value: "cc_by", label: "CC BY（会保留署名信息）" },
];

interface ImportFlowPanelProps {
  onReviewArtifact: (artifactId: string) => void;
}

function initialThreadId(): string {
  const value = new URLSearchParams(window.location.search).get("run")?.trim() ?? "";
  return value.startsWith("import-") ? value : "";
}

export function ImportFlowPanel({ onReviewArtifact }: ImportFlowPanelProps) {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState("");
  const [rights, setRights] = useState<RightsDeclaration>("user_owned");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const [threadId, setThreadId] = useState(initialThreadId);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [formError, setFormError] = useState("");

  const runQuery = useQuery({
    queryKey: ["import-run", threadId],
    queryFn: () => readImportRun(threadId),
    enabled: threadId !== "",
    refetchInterval: (query) => query.state.data?.phase === "waiting_worker" ? 1_500 : false,
  });

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new ApiError("请选择音频文件", "UPLOAD_FILE_REQUIRED", false, 422);
      if (!projectName.trim()) throw new ApiError("请输入项目名称", "PROJECT_NAME_REQUIRED", false, 422);
      if (!rightsConfirmed) throw new ApiError("请确认你有权使用这段音频", "RIGHTS_CONFIRMATION_REQUIRED", false, 422);
      const controller = new AbortController();
      abortRef.current = controller;
      return uploadAndStartImport(
        file,
        projectName.trim(),
        rights,
        operationId,
        setProgress,
        controller.signal,
      );
    },
    onSuccess: (result) => {
      abortRef.current = null;
      setThreadId(result.run.thread_id);
      setRunInUrl(result.run.thread_id);
      queryClient.setQueryData(["import-run", result.run.thread_id], result.run);
    },
    onError: () => { abortRef.current = null; },
  });

  const confirm = useMutation({
    mutationFn: (request: ConfirmImportAnalysisRequest) => confirmImportAnalysis(threadId, request),
    onSuccess: (run) => queryClient.setQueryData(["import-run", threadId], run),
  });

  const run = runQuery.data;
  useEffect(() => {
    if (run?.phase === "completed" && run.normalized_artifact_id) {
      onReviewArtifact(run.normalized_artifact_id);
    }
  }, [onReviewArtifact, run]);

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setOperationId(crypto.randomUUID());
    setProgress(null);
    setFormError("");
    if (selected) setProjectName(projectNameFor(selected.name));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    upload.mutate(undefined, { onError: (error) => setFormError(errorMessage(error)) });
  }

  function resetFlow() {
    setThreadId("");
    setRunInUrl("");
    setProgress(null);
    setFormError("");
    setOperationId(crypto.randomUUID());
  }

  return (
    <section className="import-flow" aria-labelledby="import-flow-title">
      <div className="flow-heading">
        <div><p className="eyebrow">CONTROLLED AUDIO IMPORT</p><h2 id="import-flow-title">从本地音频开始</h2></div>
        {threadId && <button className="text-button" type="button" onClick={resetFlow}>新建导入</button>}
      </div>

      {!threadId && (
        <form className="upload-form" onSubmit={submit} noValidate>
          <label className="file-drop" htmlFor="audio-file">
            <input id="audio-file" type="file" accept=".wav,.mp3,.flac,audio/wav,audio/mpeg,audio/flac" onChange={chooseFile} />
            <span className="file-drop-icon" aria-hidden="true">↥</span>
            <strong>{file ? file.name : "选择 WAV、MP3 或 FLAC"}</strong>
            <small>{file ? formatBytes(file.size) : "最大 256 MiB；浏览器先计算 SHA-256，再按分块受控上传"}</small>
          </label>
          <div className="form-grid">
            <label>项目名称<input value={projectName} onChange={(event) => setProjectName(event.target.value)} maxLength={120} /></label>
            <label>权利声明<select value={rights} onChange={(event) => setRights(event.target.value as RightsDeclaration)}>{RIGHTS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          </div>
          <label className="check-row"><input type="checkbox" checked={rightsConfirmed} onChange={(event) => setRightsConfirmed(event.target.checked)} /><span>我确认有权在本地工作台处理这段音频。</span></label>
          {progress && <UploadProgressView progress={progress} />}
          {formError && <p className="field-error" role="alert">{formError}</p>}
          <div className="action-row">
            <button className="primary-button" type="submit" disabled={upload.isPending}>{upload.isPending ? "处理中…" : "上传并开始分析"}</button>
            {upload.isPending && <button className="secondary-inline" type="button" onClick={() => abortRef.current?.abort()}>取消上传</button>}
          </div>
        </form>
      )}

      {threadId && runQuery.isPending && <RunLoading />}
      {threadId && runQuery.isError && <RunError error={runQuery.error} retry={() => void runQuery.refetch()} />}
      {run && <ImportRunView run={run} confirming={confirm.isPending} confirmationError={confirm.error} onConfirm={(value) => confirm.mutate(value)} />}
    </section>
  );
}

function ImportRunView({ run, confirming, confirmationError, onConfirm }: { run: ImportRunData; confirming: boolean; confirmationError: Error | null; onConfirm: (request: ConfirmImportAnalysisRequest) => void }) {
  return (
    <div className="run-view">
      <div className="run-status-row">
        <span className={`run-orb ${run.phase}`} />
        <div><strong>{phaseLabel(run.phase)}</strong><p title={run.thread_id}>{run.thread_id}</p></div>
        <span className="status-pill">{run.phase === "waiting_worker" ? "自动刷新" : "持久检查点"}</span>
      </div>
      {run.phase === "waiting_worker" && <RunLoading compact />}
      {run.phase === "analysis_confirmation_required" && run.analysis && (
        <AnalysisConfirmation analysis={run.analysis} disabled={confirming} onConfirm={onConfirm} />
      )}
      {confirmationError && <p className="field-error" role="alert">{errorMessage(confirmationError)}</p>}
      {run.phase === "failed" && <div className="notice danger-notice"><span className="notice-icon">×</span><div><strong>导入已停止</strong><p>{run.error_code ?? "IMPORT_FAILED"}。失败状态已保存在同一 Graph thread，不会假装完成。</p></div></div>}
      {run.phase !== "waiting_worker" && (run.source_artifact_id || run.artifact_id) && <AudioComparison run={run} />}
    </div>
  );
}

function AnalysisConfirmation({ analysis, disabled, onConfirm }: { analysis: NonNullable<ImportRunData["analysis"]>; disabled: boolean; onConfirm: (request: ConfirmImportAnalysisRequest) => void }) {
  const [bpm, setBpm] = useState(analysis.bpm?.toFixed(2) ?? "");
  const [tonic, setTonic] = useState(analysis.key_tonic ?? "C");
  const [mode, setMode] = useState<"major" | "minor">(analysis.key_mode ?? "major");
  const parsedBpm = Number(bpm);
  const bpmValid = Number.isFinite(parsedBpm) && parsedBpm >= 30 && parsedBpm <= 300;
  return (
    <div className="confirmation-card">
      <div className="analysis-summary">
        <Metric label="检测 BPM" value={analysis.bpm?.toFixed(2) ?? "未知"} confidence={analysis.bpm_confidence} />
        <Metric label="检测调性" value={analysis.key_tonic && analysis.key_mode ? `${analysis.key_tonic} ${analysis.key_mode === "major" ? "大调" : "小调"}` : "未知"} confidence={analysis.key_confidence} />
        <Metric label="项目 BPM" value={analysis.project_bpm?.toFixed(2) ?? "未知"} confidence={null} />
      </div>
      <div className="notice warning-notice"><span className="notice-icon">!</span><div><strong>分析需要你的确认</strong><p>保持音高的 time-stretch 会在确认后进入独立 Worker；不会通过 playbackRate 改变音高。</p></div></div>
      <div className="override-grid">
        <label>源 BPM<input type="number" min="30" max="300" step="0.01" value={bpm} onChange={(event) => setBpm(event.target.value)} /></label>
        <label>主音<select value={tonic} onChange={(event) => setTonic(event.target.value)}>{["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"].map((note) => <option key={note}>{note}</option>)}</select></label>
        <label>调式<select value={mode} onChange={(event) => setMode(event.target.value as "major" | "minor")}><option value="major">大调</option><option value="minor">小调</option></select></label>
      </div>
      <div className="decision-row">
        <button className="primary-button" type="button" disabled={disabled || analysis.bpm === null} onClick={() => onConfirm({ action: "confirm" })}>确认并对齐</button>
        <button className="secondary-inline" type="button" disabled={disabled || !bpmValid} onClick={() => onConfirm({ action: "override", source_bpm: parsedBpm, key_tonic: tonic, key_mode: mode })}>用修正值对齐</button>
        <button className="secondary-inline" type="button" disabled={disabled} onClick={() => onConfirm(bpmValid ? { action: "skip_alignment", source_bpm: parsedBpm } : { action: "skip_alignment" })}>不对齐，直接导入</button>
        <button className="danger-button" type="button" disabled={disabled} onClick={() => onConfirm({ action: "cancel" })}>取消本次导入</button>
      </div>
    </div>
  );
}

function AudioComparison({ run }: { run: ImportRunData }) {
  const finalId = run.artifact_id;
  const aligned = Boolean(finalId && run.normalized_artifact_id && finalId !== run.normalized_artifact_id);
  return (
    <div className="audio-comparison">
      {run.source_artifact_id && <AudioCard label="原始上传" hint="只读、校验后的源文件" artifactId={run.source_artifact_id} />}
      {finalId && <AudioCard label={aligned ? "保持音高对齐" : "标准化工作副本"} hint={aligned ? "BPM 已调整，音高保持不变" : "无需 time-stretch 或已选择跳过"} artifactId={finalId} />}
    </div>
  );
}

function AudioCard({ label, hint, artifactId }: { label: string; hint: string; artifactId: string }) {
  return <article className="audio-card"><div><strong>{label}</strong><span>{hint}</span></div><audio controls preload="metadata" src={audioContentUrl(artifactId)}>浏览器不支持音频播放。</audio></article>;
}

function UploadProgressView({ progress }: { progress: UploadProgress }) {
  const percent = progress.phase === "upload" && progress.totalBytes > 0 ? Math.round(progress.uploadedBytes / progress.totalBytes * 100) : null;
  return <div className="upload-progress" role="status"><div><span>{progress.detail}</span><b>{percent === null ? "…" : `${percent}%`}</b></div><progress max={100} value={percent ?? undefined} /></div>;
}

function Metric({ label, value, confidence }: { label: string; value: string; confidence: number | null }) {
  return <div className="mini-metric"><span>{label}</span><strong>{value}</strong>{confidence !== null && <small>置信度 {Math.round(confidence * 100)}%</small>}</div>;
}

function RunLoading({ compact = false }: { compact?: boolean }) {
  return <div className={compact ? "run-loading compact" : "run-loading"} role="status"><span /><div><strong>Worker 正在处理音频</strong><p>刷新页面也会从 PostgreSQL checkpoint 恢复，不会重跑已完成节点。</p></div></div>;
}

function RunError({ error, retry }: { error: Error; retry: () => void }) {
  return <div className="notice danger-notice" role="alert"><span className="notice-icon">!</span><div><strong>无法读取 Import Run</strong><p>{errorMessage(error)}</p><button className="secondary-inline" type="button" onClick={retry}>重试读取</button></div></div>;
}

function setRunInUrl(threadId: string) {
  const url = new URL(window.location.href);
  if (threadId) url.searchParams.set("run", threadId); else url.searchParams.delete("run");
  window.history.replaceState({}, "", url);
}

function projectNameFor(filename: string): string {
  const base = filename.replace(/\.[^.]+$/, "").trim();
  return `${base || "Imported Audio"} Project`.slice(0, 120);
}

function phaseLabel(phase: ImportRunData["phase"]): string {
  return { waiting_worker: "正在分析与处理", analysis_confirmation_required: "等待分析确认", completed: "导入与对齐已完成", failed: "导入已停止" }[phase];
}

function errorMessage(error: Error): string {
  return error instanceof ApiError ? `${error.message}（${error.code}）` : "发生了未分类的客户端错误";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}
