import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";

import { StatusBanner } from "../../app/StatusBanner";
import { navigate, navigateHref, routePath } from "../../app/routes";
import { useLocationSearch, useUnsavedNavigation } from "../../app/NavigationGuard";
import { ApiError, audioContentUrl, rehydrateArtifact } from "../../shared/api";
import type { AIRun, EditorCommand } from "../../shared/openapi";
import { readProject, readRevisionStudio } from "../projects/projectApi";
import { watchRunEvents } from "../generate/runEvents";
import { ArrangementTimeline } from "./ArrangementTimeline";
import { ClipInspector } from "./ClipInspector";
import { EditPanel } from "./EditPanel";
import { EditPreviewCard } from "./EditPreviewCard";
import { decideEditPreview } from "./editRunApi";
import { createEditRunState, reduceEditRunState } from "./editRunState";
import { createEditorState, editorReducer, projectDraft, type EditorState } from "./editorState";
import { MixerPanel } from "./MixerPanel";
import { PianoPanel } from "./PianoPanel";
import { ClassicalAccompanimentPanel } from "./ClassicalAccompanimentPanel";
import { PianoRoll } from "./PianoRoll";
import { SampleLibrary } from "./SampleLibrary";
import { commitCommandBatch, listSoundCatalog, undoCommittedRevision } from "./studioApi";
import { StudioDock } from "./StudioDock";
import { StudioInspector } from "./StudioInspector";
import { StudioToolbar } from "./StudioToolbar";
import { StudioWorkbar } from "./StudioWorkbar";
import { TrackHeaders } from "./TrackHeaders";
import { Transport } from "./Transport";
import { projectTimeline } from "./timelineProjection";
import { useAudioTransport } from "./useAudioTransport";

export function StudioPage({ projectId, revisionId }: { projectId: string; revisionId: string }) {
  const queryClient = useQueryClient();
  const search = useLocationSearch();
  const mixing = new URLSearchParams(search).get("view") === "mix";
  const studio = useQuery({ queryKey: ["revision-studio", projectId, revisionId], queryFn: () => readRevisionStudio(projectId, revisionId) });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => readProject(projectId) });
  const catalog = useQuery({ queryKey: ["sound-catalog"], queryFn: listSoundCatalog });
  const [pianoStatus,setPianoStatus]=useState("打开创作任务");
  const [recoveryFeedback, setRecoveryFeedback] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [editRun, dispatchEditRun] = useReducer(reduceEditRunState, undefined, createEditRunState);
  const [editDecisionPending, setEditDecisionPending] = useState(false);
  const [editRunId, setEditRunId] = useState<string | null>(() =>
    sessionStorage.getItem(`motif-forge:project:${projectId}:edit-run`),
  );
  const delivery = studio.data?.delivery_assets.find((asset) => asset.availability === "available") ?? studio.data?.delivery_assets[0] ?? null;
  useEffect(() => {
    if (studio.data && project.data && editor === null) setEditor(createEditorState(project.data.active_branch_id, studio.data.revision_id, studio.data.arrangement_ir));
  }, [editor, project.data, studio.data]);
  useEffect(() => {
    if (!editRunId) return;
    const controller = new AbortController();
    void watchRunEvents(editRunId, {
      onEvent: (event) => dispatchEditRun({ type: "event", event }),
      onAuthoritativeRun: (run) => {
        dispatchEditRun({ type: "authoritative", run });
        if (run.revision_id) {
          void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
          void queryClient.invalidateQueries({
            queryKey: ["revision-studio", projectId, run.revision_id],
          });
        }
      },
      onConnectionChange: (connection) => {
        if (connection === "offline_error") {
          dispatchEditRun({ type: "disconnected", errorCode: "RUN_EVENT_STREAM_FAILED" });
        }
      },
    }, controller.signal).catch(() => {
      if (!controller.signal.aborted) {
        dispatchEditRun({ type: "disconnected", errorCode: "RUN_EVENT_STREAM_FAILED" });
      }
    });
    return () => controller.abort();
  }, [editRunId, projectId, queryClient]);
  const draft = useMemo(() => editor ? projectDraft(editor) : studio.data?.arrangement_ir, [editor, studio.data]);
  const navigation = useUnsavedNavigation((editor?.historyCursor ?? 0) > 0, routePath({name:"studio",projectId,revisionId}));
  const latestEditor = useRef(editor);
  const writeRequest = useRef(0);
  useLayoutEffect(() => { latestEditor.current = editor; }, [editor]);
  const queryTrack = new URLSearchParams(search).get("track");
  useEffect(() => {
    if (!editor || !draft) return;
    const requested = queryTrack ?? editor.selection?.trackIds[0];
    const valid = draft.tracks.find(track => track.track_id === requested)?.track_id ?? draft.tracks[0]?.track_id;
    if (valid && editor.selection?.trackIds[0] !== valid) setEditor(state => state ? editorReducer(state,{type:"select",selection:{trackIds:[valid],startTick:0,endTick:draft.tracks.find(t=>t.track_id===valid)?.clips.reduce((end,clip)=>Math.max(end,clip.start_tick+clip.duration_tick),0)??0}}) : state);
  }, [queryTrack, editor, draft]);
  const projection = useMemo(() => draft ? projectTimeline(draft) : null, [draft]);
  const duration = delivery?.duration_milliseconds ? delivery.duration_milliseconds / 1000 : (projection?.durationSeconds ?? 0);
  const transport = useAudioTransport(duration, delivery?.availability === "available" ? delivery.artifact_id : null);
  const recovery = useMutation({
    mutationFn: (artifactId: string) => rehydrateArtifact(artifactId),
    onSuccess: (result) => setRecoveryFeedback(result.phase === "completed" ? "恢复任务已完成" : "恢复任务已进入持久队列"),
  });

  if (studio.isPending || project.isPending) return <StudioLoading />;
  if (studio.isError) return <StudioError error={studio.error} retry={() => void studio.refetch()} />;
  if (project.isError) return <StudioError error={project.error} retry={() => void project.refetch()} />;
  if (!studio.data || !project.data || !projection || !editor) return null;

  const dispatch = (action: Parameters<typeof editorReducer>[1]) => setEditor((state) => state ? editorReducer(state, action) : state);
  const acceptWriteResult = (requestId: number, snapshot: EditorState, revision: string) => {
    if (!navigation.isCurrent() || requestId !== writeRequest.current) return false;
    const current = latestEditor.current;
    const commands = snapshot.commands.slice(0, snapshot.historyCursor);
    if (!current || current.base.revisionId !== snapshot.base.revisionId || current.historyCursor !== commands.length || !commands.every((command, index) => current.commands[index] === command)) {
      // The submitted snapshot changed on the server. Keep newer local work
      // and surface the existing conflict state before any reset/navigation.
      dispatch({ type: "conflict", serverRevisionId: revision });
      return false;
    }
    return true;
  };
  const saveDraft = async () => {
    const requestId = ++writeRequest.current;
    const commands = editor.commands.slice(0, editor.historyCursor);
    dispatch({ type: "saving" });
    try {
      const result = await commitCommandBatch(projectId, { branch_id: editor.base.branchId, base_revision_id: editor.base.revisionId, commands, client_sequence: 0, reason: "HUMAN_STUDIO_EDIT" }, `web-edit-${crypto.randomUUID()}`);
      void queryClient.invalidateQueries({queryKey:["project",projectId]});
      if (!acceptWriteResult(requestId, editor, result.revision_id)) return;
      if (!navigation.clear()) return;
      dispatch({ type: "commitSuccess", revisionId: result.revision_id, arrangement: projectDraft(editor) });
      navigate({name:"studio",projectId,revisionId:result.revision_id});
    } catch (error) {
      if (!navigation.isCurrent() || requestId !== writeRequest.current) return;
      if (error instanceof ApiError && error.code === "REVISION_CONFLICT") dispatch({ type: "conflict", serverRevisionId: project.data.head_revision_id });
      else dispatch({ type: "saveError" });
    }
  };
  const undoRevision = async () => {
    if (studio.data.parent_revision_id === null) return;
    const requestId = ++writeRequest.current;
    try {
      const result = await undoCommittedRevision(projectId, { branch_id: editor.base.branchId, base_revision_id: editor.base.revisionId, target_revision_id: editor.base.revisionId }, `web-undo-${crypto.randomUUID()}`);
      void queryClient.invalidateQueries({queryKey:["project",projectId]});
      if (!acceptWriteResult(requestId, editor, result.revision_id)) return;
      const restored = await readRevisionStudio(projectId,result.revision_id);
      if (!acceptWriteResult(requestId, editor, result.revision_id) || !navigation.clear()) return;
      setEditor(createEditorState(editor.base.branchId,result.revision_id,restored.arrangement_ir));
      navigate({name:"studio",projectId,revisionId:result.revision_id});
    } catch { if (navigation.isCurrent() && requestId === writeRequest.current) dispatch({ type: "saveError" }); }
  };
  const moveClip = (trackId: string, clipId: string, startTick: number) => dispatch({ type: "append", command: { command_id: crypto.randomUUID(), command_type: "move_clip", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: editor.historyCursor, selection: { track_ids: [trackId], start_tick: 0, end_tick: Math.max(projection.ticksPerBar, projection.totalBars * projection.ticksPerBar) }, payload: { track_id: trackId, clip_id: clipId, start_tick: startTick } } });
  const appendCommand = (command: EditorCommand) => dispatch({ type: "append", command: { ...command, client_sequence: editor.historyCursor } });
  const chooseTrack = (trackId: string) => {
    if (!draft?.tracks.some(track => track.track_id === trackId)) return;
    dispatch({type:"select",selection:editor.selection?.trackIds[0] === trackId ? editor.selection : {trackIds:[trackId],startTick:0,endTick:draft.tracks.find(t=>t.track_id===trackId)?.clips.reduce((end,clip)=>Math.max(end,clip.start_tick+clip.duration_tick),0)??0}});
    const url = new URL(window.location.href); url.searchParams.set("track",trackId); navigateHref(url.href,true);
  };
  const chooseView = (view: "arrange" | "mix") => {const url=new URL(window.location.href);url.searchParams.set("view",view);navigateHref(url.href,true);};
  const selectedTrack = draft?.tracks.find((track) => track.track_id === editor.selection?.trackIds[0]) ?? draft?.tracks[0] ?? null;
  const selectedClip = selectedTrack?.clips.find((clip) => clip.clip_id === editor.selection?.clipId) ?? selectedTrack?.clips[0] ?? null;

  const rootReady = project.data.storage_root_status === "ready";
  const classical=editor.base.arrangement.provenance?.some(ref=>ref.kind==="asset"&&ref.ref.startsWith("score:"))??false;
  const handleRunCreated = (run: AIRun) => {
    sessionStorage.setItem(`motif-forge:project:${projectId}:edit-run`, run.run_id);
    setEditRunId(run.run_id);
    dispatchEditRun({ type: "authoritative", run });
  };
  const decidePreview = async (action: "approve" | "reject" | "cancel") => {
    if (!editRun.runId || !editRun.preview) return;
    setEditDecisionPending(true);
    try {
      const run = await decideEditPreview(editRun.runId, {
        action,
        preview_id: editRun.preview.preview_id,
        expected_candidate_content_hash: editRun.preview.candidate_content_hash,
        actor_id: "human:web",
        approval_assertion: `Web user confirmed rendered edit: ${action}`,
        note: "",
      }, `web-edit-decision:${editRun.runId}:${action}`);
      dispatchEditRun({ type: "authoritative", run });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        dispatchEditRun({ type: "conflict", serverRevisionId: project.data.head_revision_id });
      } else dispatchEditRun({ type: "disconnected", errorCode: errorMessage(error as Error) });
    } finally {
      setEditDecisionPending(false);
    }
  };
  return (
    <section className="studio-page" data-view={mixing?"mix":"arrange"} aria-labelledby="studio-title">
      <StudioWorkbar
        projectName={project.data.name}
        revisionId={revisionId}
        trackCount={studio.data.arrangement_ir.tracks.length}
        bars={projection.totalBars}
        bpm={studio.data.arrangement_ir.tempo_map?.[0]?.bpm ?? 120}
        actions={<><a className="secondary-inline" href={`/projects/${encodeURIComponent(projectId)}/exports/${encodeURIComponent(revisionId)}`}>查看导出</a>{studio.data.source_run_id && <a className="secondary-inline" href={`/runs/${encodeURIComponent(studio.data.source_run_id)}/inspect`}>查看执行记录</a>}</>}
        toolbar={<StudioToolbar state={editor} hasParentRevision={studio.data.parent_revision_id !== null} onUndo={() => dispatch({ type: "undo" })} onRedo={() => dispatch({ type: "redo" })} onSave={() => void saveDraft()} onUndoRevision={() => void undoRevision()} />}
      />
      <nav className="workspace-views" aria-label="工作区视图"><button type="button" aria-pressed={!mixing} onClick={()=>chooseView("arrange")}>编排</button><button type="button" aria-pressed={mixing} onClick={()=>chooseView("mix")}>混音</button></nav>
      <p className="mobile-review-note">手机上可以试听和查看作品；精细编辑请使用桌面浏览器。</p>
      {studio.data.bundle_id === null && <StatusBanner tone="warning" message="作品已保存，导出尚未完整完成" detail="编排内容已保留。可以继续编辑，或前往导出页查看已完成的文件。" />}
      {!rootReady && <StatusBanner tone="danger" message="作品存储位置暂不可用" detail={`存储状态：${project.data.storage_root_status}。请检查外置磁盘连接；现有作品记录仍然保留。`} />}
          <section className="studio-panel" aria-labelledby="transport-title"><div className="panel-heading"><div><h2 id="transport-title">作品试听</h2></div>{delivery && <span className={`status-pill ${delivery.availability}`}>{availabilityLabel(delivery.availability)}</span>}</div><p className="saved-audio-note">播放：保存版 {revisionId.slice(0,8)}{editor.historyCursor>0?" · 草稿未渲染":""}</p>{(draft?.schema_version === "arrangement-ir.v3" || draft?.schema_version === "arrangement-ir.v4" || draft?.schema_version === "arrangement-ir.v5") && <a className="secondary-inline" href={`/projects/${encodeURIComponent(projectId)}/exports/${encodeURIComponent(revisionId)}`}>生成此保存版试听/导出</a>}<DeliveryState delivery={delivery} rootReady={rootReady} recoveryPending={recovery.isPending} recoveryFeedback={recoveryFeedback} recoveryError={recovery.isError ? errorMessage(recovery.error) : null} onRecover={(artifactId) => recovery.mutate(artifactId)} transport={transport} duration={duration} /></section>
      <div className="studio-main-workspace">
        <div className="studio-arrangement-main" aria-label="Arrangement 主工作区">
          {projection.tracks.length === 0 ? <section className="empty-state studio-empty"><div className="empty-wave" aria-hidden="true">···</div><h2>这个版本还没有音轨</h2><p>可以返回作品列表新建编曲，或导入已有音频作为起点。</p></section> : <section hidden={mixing} className="studio-panel arrangement-panel" aria-labelledby="arrangement-title">
            <div className="panel-heading"><div><h2 id="arrangement-title">编排</h2></div><span className="status-pill available">{editor.saveState === "clean" ? "已保存" : "有未保存修改"}</span></div>
            <div className="arrangement-workspace"><TrackHeaders tracks={projection.tracks} selectedTrackId={selectedTrack?.track_id ?? ""} onSelectTrack={chooseTrack} /><ArrangementTimeline projection={projection} currentTime={transport.currentTime} onMoveClip={moveClip} onSelectClip={(trackId, clipId, startTick, endTick) => {const url=new URL(window.location.href);url.searchParams.set("track",trackId);navigateHref(url.href,true);dispatch({ type: "select", selection: { trackIds: [trackId], clipId, startTick, endTick } });}} /></div>
            <div className="section-ledger" aria-label="段落列表">{projection.sections.map((section) => <span key={section.sectionId}><strong>{section.label}</strong> · {Math.round(section.energy * 100)}%</span>)}</div>
          </section>}
      <StudioDock workspaceMode={mixing?"mix":"arrange"}
        piano={selectedTrack && selectedClip?.clip_type === "note" ? <PianoRoll trackId={selectedTrack.track_id} clip={selectedClip} onCommand={appendCommand} /> : <p>选择一个音符片段打开钢琴卷帘。</p>}
        mixer={<MixerPanel selectedTrackId={selectedTrack?.track_id ?? ""} onSelectTrack={chooseTrack} output={<section className="master-output" aria-label="主输出"><strong>主输出</strong><span>保存版 {revisionId.slice(0,8)} · {delivery?availabilityLabel(delivery.availability):"尚未生成音频"}</span><a href={`/projects/${encodeURIComponent(projectId)}/exports/${encodeURIComponent(revisionId)}`}>导出</a></section>} tracks={draft?.tracks ?? []} pianoArrangement={draft ?? editor.base.arrangement} savedArrangement={editor.base.arrangement} disabled={!rootReady || editor.saveState === "saving" || editor.saveState === "conflict"} onCommand={appendCommand} />}
        inspector={<ClipInspector trackId={selectedTrack?.track_id ?? ""} clip={selectedClip} onCommand={appendCommand} />}
        library={<>{editor.base.arrangement.schema_version !== "arrangement-ir.v1" && <p>当前版本使用已确认的钢琴音源，普通音色切换暂不支持。</p>}<SampleLibrary entries={catalog.data ?? []} onChoose={selectedTrack && editor.base.arrangement.schema_version === "arrangement-ir.v1" ? (entry) => appendCommand({ command_id: crypto.randomUUID(), command_type: "set_track_param", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [selectedTrack.track_id] }, payload: { track_id: selectedTrack.track_id, parameter: "instrument_ref", value: entry.preset_id } }) : undefined} /></>}
      />
        </div>
        <StudioInspector approvalKey={editRun.mode === "waiting_approval" ? editRun.preview?.candidate_content_hash : new URLSearchParams(search).get("piano_preview") ?? project.data.recoverable_piano_preview?.thread_id} status={editRun.mode === "waiting_approval" || project.data.recoverable_piano_preview?.phase === "waiting_piano_approval" ? "待确认" : editRun.mode !== "idle" ? editRunModeLabel(editRun.mode) : pianoStatus}>
          {classical?<ClassicalAccompanimentPanel projectId={projectId} branchId={editor.base.branchId} revisionId={editor.base.revisionId}
            arrangement={editor.base.arrangement} selection={editor.selection} dirty={editor.historyCursor>0}
            rootReady={rootReady} headRevisionId={project.data.head_revision_id}
            onTaskStatusChange={setPianoStatus} recovery={{info:project.data.piano_preview_recovery,candidate:project.data.recoverable_piano_preview,reading:project.isFetching,onRead:async()=>{const result=await project.refetch();if(result.isError)throw result.error;}}} onSaved={(next)=>{void queryClient.invalidateQueries({queryKey:["project",projectId]});navigate({name:"studio",projectId,revisionId:next});}}/>:<PianoPanel projectId={projectId} branchId={editor.base.branchId} revisionId={editor.base.revisionId}
            arrangement={editor.base.arrangement} selection={editor.selection} dirty={editor.historyCursor>0}
            rootReady={rootReady} headRevisionId={project.data.head_revision_id}
            onTaskStatusChange={setPianoStatus} recovery={{info:project.data.piano_preview_recovery,candidate:project.data.recoverable_piano_preview,reading:project.isFetching,onRead:async()=>{const result=await project.refetch();if(result.isError)throw result.error;}}} onSaved={(next)=>{void queryClient.invalidateQueries({queryKey:["project",projectId]});navigate({name:"studio",projectId,revisionId:next});}}/>}
          {!classical&&<EditPanel projectId={projectId} branchId={editor.base.branchId} baseRevisionId={editor.base.revisionId} selection={editor.selection} lockedRanges={[]} rootReady={rootReady} onRunCreated={handleRunCreated} />}
          {editRun.mode !== "idle" && <section className="edit-run-status" aria-live="polite"><strong>{editRunModeLabel(editRun.mode)}</strong>{editRun.errorCode && <span>{editRun.errorCode}</span>}{editRun.mode === "committed" && editRun.revisionId && <button className="primary-button" type="button" onClick={() => navigate({ name: "studio", projectId, revisionId: editRun.revisionId as string })}>打开修改后的版本</button>}</section>}
          {editRun.preview && <EditPreviewCard preview={editRun.preview} busy={editDecisionPending} rootReady={rootReady} onDecision={(action) => void decidePreview(action)} />}

        </StudioInspector>
      </div>

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
  if (!delivery) return <p className="delivery-guidance">这个版本还没有可试听的 MP3。请在导出页查看处理进度。</p>;
  if (!rootReady) return <p className="delivery-guidance">重新连接作品存储位置后，即可恢复文件和播放。</p>;
  if (delivery.availability === "available") return <Transport audioRef={transport.audioRef} src={audioContentUrl(delivery.artifact_id)} duration={duration} currentTime={transport.currentTime} isPlaying={transport.isPlaying} mediaError={transport.mediaError} onPlay={transport.play} onPause={transport.pause} onStop={transport.stop} onSeek={transport.seek} mediaProps={transport.mediaProps} />;
  if (delivery.availability === "rehydrating") return <p className="delivery-guidance">正在重新生成 MP3，完成后刷新即可播放</p>;
  if (delivery.availability === "missing") return <p className="delivery-guidance is-danger">恢复 MP3 所需的源文件缺失，请检查原始素材</p>;
  return (
    <div className="delivery-recovery">
      <p>为节省空间，MP3 缓存已回收。编排仍然保留，可以重新生成试听文件。</p>
      <button className="secondary-inline" type="button" disabled={recoveryPending} onClick={() => onRecover(delivery.artifact_id)}>{recoveryPending ? "提交中…" : "恢复 MP3"}</button>
      {recoveryFeedback && <span role="status">{recoveryFeedback}</span>}
      {recoveryError && <span className="field-error" role="alert">{recoveryError}</span>}
    </div>
  );
}

function StudioLoading() { return <section className="loading-state"><div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div><h2>正在打开 Studio</h2><p>正在加载音轨、编排与当前版本的试听文件。</p></section>; }
function StudioError({ error, retry }: { error: Error; retry: () => void }) { return <section className="error-state" role="alert"><span>!</span><div><h2>无法打开 Studio</h2><p>{errorMessage(error)}</p><button type="button" onClick={retry}>重试</button></div></section>; }
function errorMessage(error: Error): string { return error instanceof ApiError ? `${error.message}（${error.code}）` : error.message || "客户端发生未知错误"; }
function availabilityLabel(value: "available" | "evicted" | "rehydrating" | "missing"): string { return ({ available: "可播放", evicted: "已回收", rehydrating: "重建中", missing: "缺失" })[value]; }
function editRunModeLabel(value: import("./editRunState").EditRunMode): string {
  return ({ idle: "待命", submitting: "正在提交", planning: "正在规划与模拟", rendering_preview: "正在渲染 Preview", waiting_approval: "等待 Preview 审批", committed: "已提交新 Revision", rejected: "Preview 已拒绝", cancelled: "Edit Run 已取消", failed: "Edit Run 失败", disconnected: "事件连接中断，可刷新恢复", conflict: "Base 已变化，本地 Draft 已保留" })[value];
}
