import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { StatusBanner } from "../../app/StatusBanner";
import { ApiError, audioContentUrl, rehydrateArtifact } from "../../shared/api";
import type { EditorCommand } from "../../shared/openapi";
import { readProject, readRevisionStudio } from "../projects/projectApi";
import { ArrangementTimeline } from "./ArrangementTimeline";
import { ClipInspector } from "./ClipInspector";
import { createEditorState, editorReducer, projectDraft, type EditorState } from "./editorState";
import { MixerPanel } from "./MixerPanel";
import { PianoRoll } from "./PianoRoll";
import { SampleLibrary } from "./SampleLibrary";
import { commitCommandBatch, listSoundCatalog, undoCommittedRevision } from "./studioApi";
import { StudioDock } from "./StudioDock";
import { StudioToolbar } from "./StudioToolbar";
import { TrackHeaders } from "./TrackHeaders";
import { Transport } from "./Transport";
import { projectTimeline } from "./timelineProjection";
import { useAudioTransport } from "./useAudioTransport";

export function StudioPage({ projectId, revisionId }: { projectId: string; revisionId: string }) {
  const studio = useQuery({ queryKey: ["revision-studio", projectId, revisionId], queryFn: () => readRevisionStudio(projectId, revisionId) });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => readProject(projectId) });
  const catalog = useQuery({ queryKey: ["sound-catalog"], queryFn: listSoundCatalog });
  const [recoveryFeedback, setRecoveryFeedback] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const delivery = studio.data?.delivery_assets.find((asset) => asset.quality_profile === "delivery-mp3.v1") ?? null;
  useEffect(() => {
    if (studio.data && project.data && editor === null) setEditor(createEditorState(project.data.active_branch_id, studio.data.revision_id, studio.data.arrangement_ir));
  }, [editor, project.data, studio.data]);
  const draft = useMemo(() => editor ? projectDraft(editor) : studio.data?.arrangement_ir, [editor, studio.data]);
  const projection = useMemo(() => draft ? projectTimeline(draft) : null, [draft]);
  const duration = delivery?.duration_milliseconds ? delivery.duration_milliseconds / 1000 : (projection?.durationSeconds ?? 0);
  const transport = useAudioTransport(duration);
  const recovery = useMutation({
    mutationFn: (artifactId: string) => rehydrateArtifact(artifactId),
    onSuccess: (result) => setRecoveryFeedback(result.phase === "completed" ? "恢复任务已完成" : "恢复任务已进入持久队列"),
  });

  if (studio.isPending || project.isPending) return <StudioLoading />;
  if (studio.isError) return <StudioError error={studio.error} retry={() => void studio.refetch()} />;
  if (project.isError) return <StudioError error={project.error} retry={() => void project.refetch()} />;
  if (!studio.data || !project.data || !projection || !editor) return null;

  const dispatch = (action: Parameters<typeof editorReducer>[1]) => setEditor((state) => state ? editorReducer(state, action) : state);
  const saveDraft = async () => {
    const commands = editor.commands.slice(0, editor.historyCursor);
    dispatch({ type: "saving" });
    try {
      const result = await commitCommandBatch(projectId, { branch_id: editor.base.branchId, base_revision_id: editor.base.revisionId, commands, client_sequence: 0, reason: "HUMAN_STUDIO_EDIT" }, `web-edit-${crypto.randomUUID()}`);
      dispatch({ type: "commitSuccess", revisionId: result.revision_id, arrangement: projectDraft(editor) });
    } catch (error) {
      if (error instanceof ApiError && error.code === "REVISION_CONFLICT") dispatch({ type: "conflict", serverRevisionId: project.data.head_revision_id });
      else dispatch({ type: "saveError" });
    }
  };
  const undoRevision = async () => {
    try {
      const result = await undoCommittedRevision(projectId, { branch_id: editor.base.branchId, base_revision_id: editor.base.revisionId, target_revision_id: editor.base.revisionId }, `web-undo-${crypto.randomUUID()}`);
      const refreshed = await studio.refetch();
      if (refreshed.data) setEditor(createEditorState(editor.base.branchId, result.revision_id, refreshed.data.arrangement_ir));
    } catch { dispatch({ type: "saveError" }); }
  };
  const moveClip = (trackId: string, clipId: string, startTick: number) => dispatch({ type: "append", command: { command_id: crypto.randomUUID(), command_type: "move_clip", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: editor.historyCursor, selection: { track_ids: [trackId], start_tick: 0, end_tick: Math.max(projection.ticksPerBar, projection.totalBars * projection.ticksPerBar) }, payload: { track_id: trackId, clip_id: clipId, start_tick: startTick } } });
  const appendCommand = (command: EditorCommand) => dispatch({ type: "append", command: { ...command, client_sequence: editor.historyCursor } });
  const selectedTrack = draft?.tracks.find((track) => track.track_id === editor.selection?.trackIds[0]) ?? draft?.tracks[0] ?? null;
  const selectedClip = selectedTrack?.clips.find((clip) => clip.clip_id === editor.selection?.clipId) ?? selectedTrack?.clips[0] ?? null;

  const rootReady = project.data.storage_root_status === "ready";
  return (
    <section className="studio-page" aria-labelledby="studio-title">
      <header className="studio-hero">
        <div><p className="eyebrow">ARRANGEMENT / REVISION STUDIO</p><h1 id="studio-title">{project.data.name} / Revision</h1><p>在不可变 Base 上编辑本地 Draft，确认后保存为新的 Revision。</p></div>
        <div className="studio-meta"><span>{studio.data.arrangement_ir.tracks.length} tracks</span><span>{projection.totalBars} bars</span><span>{studio.data.arrangement_ir.tempo_map?.[0]?.bpm ?? 120} BPM</span></div>
      </header>

      {studio.data.bundle_id === null && <StatusBanner tone="warning" message="部分成功 Revision" detail="安全 Revision 已保留，但完整 Bundle 尚未形成。" />}
      {!rootReady && <StatusBanner tone="danger" message="外置 Artifact Root 当前不可用" detail={`存储状态：${project.data.storage_root_status}。页面不会改用内部磁盘。`} />}
      <StudioToolbar state={editor} onUndo={() => dispatch({ type: "undo" })} onRedo={() => dispatch({ type: "redo" })} onSave={() => void saveDraft()} onUndoRevision={() => void undoRevision()} />

      <section className="studio-panel" aria-labelledby="transport-title">
        <div className="panel-heading"><div><p className="eyebrow">DELIVERY MP3</p><h2 id="transport-title">作品试听</h2></div>{delivery && <span className={`status-pill ${delivery.availability}`}>{availabilityLabel(delivery.availability)}</span>}</div>
        <DeliveryState
          delivery={delivery}
          rootReady={rootReady}
          recoveryPending={recovery.isPending}
          recoveryFeedback={recoveryFeedback}
          recoveryError={recovery.isError ? errorMessage(recovery.error) : null}
          onRecover={(artifactId) => recovery.mutate(artifactId)}
          transport={transport}
          duration={duration}
        />
      </section>

      {projection.tracks.length === 0 ? (
        <section className="empty-state studio-empty"><div className="empty-wave" aria-hidden="true">···</div><h2>这个 Revision 还没有可显示的轨道</h2><p>ArrangementIR 已读取，但 tracks 为空；页面不会伪造编排内容。</p></section>
      ) : (
        <section className="studio-panel arrangement-panel" aria-labelledby="arrangement-title">
          <div className="panel-heading"><div><p className="eyebrow">ARRANGEMENT IR / PPQ {draft?.ppq}</p><h2 id="arrangement-title">可编辑时间线</h2></div><span className="status-pill available">{editor.saveState === "clean" ? "已持久化" : "Draft"}</span></div>
          <div className="arrangement-workspace"><TrackHeaders tracks={projection.tracks} /><ArrangementTimeline projection={projection} currentTime={transport.currentTime} onMoveClip={moveClip} onSelectClip={(trackId, clipId, startTick, endTick) => dispatch({ type: "select", selection: { trackIds: [trackId], clipId, startTick, endTick } })} /></div>
          <div className="section-ledger" aria-label="段落列表">{projection.sections.map((section) => <span key={section.sectionId}><strong>{section.label}</strong> · {Math.round(section.energy * 100)}%</span>)}</div>
        </section>
      )}
      <StudioDock
        piano={selectedTrack && selectedClip?.clip_type === "note" ? <PianoRoll trackId={selectedTrack.track_id} clip={selectedClip} onCommand={appendCommand} /> : <p>选择一个音符片段打开钢琴卷帘。</p>}
        mixer={<MixerPanel tracks={(draft?.tracks ?? []).map((track) => ({ track_id: track.track_id, name: track.name, gain_db: track.gain_db, pan: track.pan, mute: track.mute, solo: track.solo }))} onCommand={appendCommand} />}
        inspector={<ClipInspector trackId={selectedTrack?.track_id ?? ""} clip={selectedClip} onCommand={appendCommand} />}
        library={<SampleLibrary entries={catalog.data ?? []} onChoose={selectedTrack ? (entry) => appendCommand({ command_id: crypto.randomUUID(), command_type: "set_track_param", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [selectedTrack.track_id] }, payload: { track_id: selectedTrack.track_id, parameter: "instrument_ref", value: entry.preset_id } }) : undefined} />}
      />
    </section>
  );
}

type AudioTransport = ReturnType<typeof useAudioTransport>;

function DeliveryState({ delivery, rootReady, recoveryPending, recoveryFeedback, recoveryError, onRecover, transport, duration }: {
  delivery: { artifact_id: string; availability: "available" | "evicted" | "rehydrating" | "missing" } | null;
  rootReady: boolean;
  recoveryPending: boolean;
  recoveryFeedback: string | null;
  recoveryError: string | null;
  onRecover: (artifactId: string) => void;
  transport: AudioTransport;
  duration: number;
}) {
  if (!delivery) return <p className="delivery-guidance">这个 Revision 尚未登记 delivery MP3。</p>;
  if (!rootReady) return <p className="delivery-guidance">恢复与播放将在外置 Root 恢复后可用。</p>;
  if (delivery.availability === "available") return <Transport audioRef={transport.audioRef} src={audioContentUrl(delivery.artifact_id)} duration={duration} currentTime={transport.currentTime} isPlaying={transport.isPlaying} mediaError={transport.mediaError} onPlay={transport.play} onPause={transport.pause} onStop={transport.stop} onSeek={transport.seek} mediaProps={transport.mediaProps} />;
  if (delivery.availability === "rehydrating") return <p className="delivery-guidance">MP3 正在由持久 Worker 重建</p>;
  if (delivery.availability === "missing") return <p className="delivery-guidance is-danger">MP3 的重建依赖缺失</p>;
  return (
    <div className="delivery-recovery">
      <p>MP3 已被回收，ArrangementIR 与 Artifact 记录仍然保留。</p>
      <button className="secondary-inline" type="button" disabled={recoveryPending} onClick={() => onRecover(delivery.artifact_id)}>{recoveryPending ? "提交中…" : "恢复 MP3"}</button>
      {recoveryFeedback && <span role="status">{recoveryFeedback}</span>}
      {recoveryError && <span className="field-error" role="alert">{recoveryError}</span>}
    </div>
  );
}

function StudioLoading() { return <section className="loading-state"><div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div><h2>读取 Revision Studio</h2><p>正在读取 ArrangementIR、Delivery Artifact 与外置 Root 状态。</p></section>; }
function StudioError({ error, retry }: { error: Error; retry: () => void }) { return <section className="error-state" role="alert"><span>!</span><div><h2>无法打开 Studio</h2><p>{errorMessage(error)}</p><button type="button" onClick={retry}>重试</button></div></section>; }
function errorMessage(error: Error): string { return error instanceof ApiError ? `${error.message}（${error.code}）` : error.message || "客户端发生未知错误"; }
function availabilityLabel(value: "available" | "evicted" | "rehydrating" | "missing"): string { return ({ available: "可播放", evicted: "已回收", rehydrating: "重建中", missing: "缺失" })[value]; }
