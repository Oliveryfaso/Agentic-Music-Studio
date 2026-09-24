import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useCallback, useState } from "react";
import { AppShell } from "../../app/AppShell";

import {
  ApiError,
  FeatureArtifactData,
  isUuid,
  listAudioFeatures,
  readFeatureArtifact,
  rehydrateArtifact,
} from "../../shared/api";
import { AnalysisPanel } from "./AnalysisPanel";
import { ImportFlowPanel } from "./ImportFlowPanel";
import { readProject } from "../projects/projectApi";
import { parseAnalysisPayload, parseWaveformPayload } from "./featurePayloads";
import { WaveformCanvas } from "./WaveformCanvas";

function initialArtifactId(): string {
  return new URLSearchParams(window.location.search).get("artifact")?.trim() ?? "";
}

export function ImportReviewPage({ projectId }: { projectId?: string }) {
  const [draftId, setDraftId] = useState(initialArtifactId);
  const [sourceArtifactId, setSourceArtifactId] = useState(() => {
    const value = initialArtifactId();
    return isUuid(value) ? value : "";
  });
  const [validationMessage, setValidationMessage] = useState("");
  const targetProject = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => readProject(projectId as string),
    enabled: projectId !== undefined,
  });

  const reviewArtifact = useCallback((artifactId: string) => {
    setDraftId(artifactId);
    setSourceArtifactId(artifactId);
    const url = new URL(window.location.href);
    url.searchParams.set("artifact", artifactId);
    window.history.replaceState({}, "", url);
  }, []);

  const featureSet = useQuery({
    queryKey: ["audio-features", sourceArtifactId],
    queryFn: () => listAudioFeatures(sourceArtifactId),
    enabled: sourceArtifactId !== "",
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = draftId.trim();
    if (!isUuid(value)) {
      setValidationMessage("请输入完整的源 Audio Artifact UUID");
      return;
    }
    setValidationMessage("");
    setSourceArtifactId(value);
    const url = new URL(window.location.href);
    url.searchParams.set("artifact", value);
    window.history.replaceState({}, "", url);
  }

  return (
    <AppShell>
        <a className="back-link" href="/">← 返回作品</a>
        <section className="hero">
          <div>
            <p className="eyebrow">BRING YOUR OWN SOUND</p>
            <h1>让已有的声音，成为新的起点。</h1>
            <p>导入音频或分轨，查看波形、速度与调性。确认分析结果后，再把素材加入编排；原始文件会保留。</p>
          </div>
        </section>

        {projectId && targetProject.isPending && <InlineLoading label="正在读取作品和最新版本…" />}
        {projectId && targetProject.isError && <ErrorState error={targetProject.error} retry={() => void targetProject.refetch()} />}
        {!projectId && <ImportFlowPanel onReviewArtifact={reviewArtifact} />}
        {projectId && targetProject.data && (
          <ImportFlowPanel
            onReviewArtifact={reviewArtifact}
            projectTarget={targetProject.data}
            onRefreshProject={() => readProject(projectId)}
          />
        )}

        <details className="developer-entry">
          <summary>开发者入口：按 Artifact UUID 查看</summary>
          <form className="artifact-form" onSubmit={submit} noValidate>
            <label htmlFor="artifact-id">源 Audio Artifact ID</label>
            <div className="input-row">
              <input
                id="artifact-id"
                value={draftId}
                onChange={(event) => setDraftId(event.target.value)}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                spellCheck={false}
                aria-describedby={validationMessage ? "artifact-error" : "artifact-help"}
              />
              <button type="submit">载入分析</button>
            </div>
            {validationMessage ? <p id="artifact-error" className="field-error">{validationMessage}</p> : <p id="artifact-help">仅用于调试历史 Artifact；正常使用不需要复制 UUID。</p>}
          </form>
        </details>

        {!sourceArtifactId && <EmptyState />}
        {sourceArtifactId && featureSet.isPending && <LoadingState />}
        {sourceArtifactId && featureSet.isError && (
          <ErrorState error={featureSet.error} retry={() => void featureSet.refetch()} />
        )}
        {featureSet.data && featureSet.data.features.length === 0 && <NoFeaturesState />}
        {featureSet.data && featureSet.data.features.length > 0 && (
          <FeatureWorkspace sourceArtifactId={sourceArtifactId} features={featureSet.data.features} />
        )}
    </AppShell>
  );
}

function FeatureWorkspace({ sourceArtifactId, features }: { sourceArtifactId: string; features: FeatureArtifactData[] }) {
  const queryClient = useQueryClient();
  const available = features.filter((feature) => feature.availability === "available");
  const payloadQueries = useQueries({
    queries: available.map((feature) => ({
      queryKey: ["feature-artifact", feature.artifact_id],
      queryFn: () => readFeatureArtifact(feature.artifact_id),
      retry: 1,
    })),
  });
  const loaded = payloadQueries.map((query) => query.data).filter((item): item is FeatureArtifactData => item !== undefined);
  const waveformFeature = loaded.find((feature) => feature.feature_profile === "waveform-peaks.v1");
  const analysisFeature = loaded.find(
    (feature) => feature.feature_profile === "imported-audio-analysis.v1",
  );
  const waveform = waveformFeature?.payload ? parseWaveformPayload(waveformFeature.payload) : null;
  const analysis = analysisFeature?.payload ? parseAnalysisPayload(analysisFeature.payload) : null;
  const anyLoading = payloadQueries.some((query) => query.isPending);
  const failed = payloadQueries.filter((query) => query.isError);

  const recovery = useMutation({
    mutationFn: rehydrateArtifact,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["audio-features", sourceArtifactId] });
    },
  });

  return (
    <div className="workspace-grid">
      <div className="workspace-main">
        {anyLoading && <InlineLoading label="正在读取波形与分析结果…" />}
        {failed.length > 0 && (
          <div className="notice danger-notice" role="alert">
            <span className="notice-icon">×</span>
            <div><strong>部分分析结果读取失败</strong><p>其余结果仍可查看。请确认作品存储盘已连接，再刷新重试。</p></div>
          </div>
        )}
        {waveform && <WaveformCanvas waveform={waveform} />}
        {analysis && <AnalysisPanel analysis={analysis} />}
        {!anyLoading && !waveform && !analysis && available.length > 0 && (
          <div className="panel empty-panel"><strong>没有可呈现的 v1 Feature</strong><p>返回的 Profile 或 payload 与当前 Web 合同不匹配。</p></div>
        )}
      </div>
      <aside className="artifact-inspector" aria-labelledby="artifact-inspector-title">
        <div className="panel-heading">
          <div><p className="eyebrow">ARTIFACT LEDGER</p><h2 id="artifact-inspector-title">分析产物</h2></div>
          <span className="count-badge">{features.length}</span>
        </div>
        <p className="source-id" title={sourceArtifactId}>{sourceArtifactId}</p>
        <div className="artifact-list">
          {features.map((feature) => (
            <ArtifactRow
              key={feature.artifact_id}
              feature={feature}
              recovering={recovery.isPending && recovery.variables === feature.artifact_id}
              onRecover={() => recovery.mutate(feature.artifact_id)}
            />
          ))}
        </div>
        {recovery.data && <p className="recovery-feedback" role="status">恢复任务 {recovery.data.phase === "completed" ? "已完成" : "已进入持久队列"}</p>}
        {recovery.isError && <p className="field-error" role="alert">{errorMessage(recovery.error)}</p>}
      </aside>
    </div>
  );
}

function ArtifactRow({ feature, recovering, onRecover }: { feature: FeatureArtifactData; recovering: boolean; onRecover: () => void }) {
  const label = feature.feature_profile === "waveform-peaks.v1" ? "波形 Peaks" : feature.feature_profile === "imported-audio-analysis.v1" ? "BPM / 调性" : feature.feature_profile;
  return (
    <article className="artifact-row">
      <div className="artifact-row-head">
        <strong>{label}</strong>
        <span className={`status-pill ${feature.availability}`}>{availabilityLabel(feature.availability)}</span>
      </div>
      <p>{feature.feature_schema_version}</p>
      <div className="artifact-meta"><span>{formatBytes(feature.byte_size)}</span><span>{feature.content_hash.slice(0, 10)}…</span></div>
      {feature.availability === "evicted" && <button className="secondary-button" type="button" onClick={onRecover} disabled={recovering}>{recovering ? "提交中…" : "显式重建"}</button>}
      {feature.availability === "rehydrating" && <p className="artifact-guidance">持久 Worker 正在重建，刷新后仍可恢复状态。</p>}
      {feature.availability === "missing" && <p className="artifact-guidance is-danger">重建依赖缺失；不会无限重试。</p>}
    </article>
  );
}

function EmptyState() {
  return <section className="empty-state"><div className="empty-wave" aria-hidden="true">∿</div><h2>从一段声音开始</h2><p>选择上方的音频文件并确认使用权利。分析完成后，可以在这里查看波形、速度和调性。</p></section>;
}

function NoFeaturesState() {
  return <section className="empty-state"><div className="empty-wave" aria-hidden="true">···</div><h2>波形与分析结果尚未就绪</h2><p>原始音频已保存。请查看上方的导入进度，处理完成后刷新此页。</p></section>;
}

function LoadingState() {
  return <section className="loading-state" aria-live="polite"><div className="spectral-loader"><i /><i /><i /><i /><i /></div><h2>正在读取音频分析</h2><p>正在核对已保存的波形和分析结果，请稍候。</p></section>;
}

function InlineLoading({ label }: { label: string }) {
  return <div className="inline-loading" role="status"><span /><p>{label}</p></div>;
}

function ErrorState({ error, retry }: { error: Error; retry: () => void }) {
  return <section className="error-state" role="alert"><span>!</span><div><h2>无法载入导入分析</h2><p>{errorMessage(error)}</p><button type="button" onClick={retry}>重试</button></div></section>;
}

function errorMessage(error: Error): string {
  if (error instanceof ApiError) return `${error.message}（${error.code}）`;
  return "发生了未分类的客户端错误";
}

function availabilityLabel(value: FeatureArtifactData["availability"]): string {
  return { available: "可用", evicted: "已回收", missing: "缺失", rehydrating: "重建中" }[value];
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}
