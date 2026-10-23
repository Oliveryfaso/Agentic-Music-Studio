import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RevisionStudio } from "../../shared/openapi";
import { StudioPage } from "./StudioPage";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const REVISION_ID = "22222222-2222-4222-8222-222222222222";
const ARTIFACT_ID = "33333333-3333-4333-8333-333333333333";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Read-only Arrangement Studio", () => {
  it("orders a compact workbar, arrangement main region, inspector, and dock", async () => {
    stubReads(studio("available"), "ready");
    renderStudio();

    const workbar = await screen.findByLabelText("Studio 工作栏");
    const arrangement = screen.getByLabelText("Arrangement 主工作区");
    const inspector = screen.getByRole("complementary", { name: "Studio Inspector" });
    const dock = screen.getByLabelText("Studio Dock");
    expect(workbar.compareDocumentPosition(arrangement)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(arrangement.compareDocumentPosition(inspector)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(arrangement.contains(dock)).toBe(true);
    expect(arrangement.compareDocumentPosition(screen.getByText("AI 选区编辑"))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(workbar.compareDocumentPosition(screen.getByText("作品试听"))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(arrangement.compareDocumentPosition(screen.getByText("作品试听"))).toBe(Node.DOCUMENT_POSITION_PRECEDING);
  });

  it("keeps pointer edits local until Save Revision", async () => {
    let commits = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith(`/revisions/${REVISION_ID}/studio`)) return jsonResponse({ data: studio("available") });
      if (path === `/api/v1/projects/${PROJECT_ID}`) return jsonResponse({ data: project("ready") });
      if (path.endsWith("/command-batches") && init?.method === "POST") {
        commits += 1;
        return new Response(JSON.stringify({ data: { branch_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", revision_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", content_hash: "a".repeat(64), actual_change_impact: "L0", render_state: "dirty", replayed: false } }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`unexpected request ${path}`);
    }));
    renderStudio();
    const clip = (await screen.findAllByRole("button", { name: /Clip A very long atmospheric pad/ }))[0]!;
    const canvas = screen.getByLabelText("时间线画布");
    fireEvent.pointerDown(clip, { clientX: 100, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 212, pointerId: 1 });
    expect(screen.getByText("1 个未保存修改")).toBeInTheDocument();
    expect(commits).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));
    await waitFor(() => expect(commits).toBe(1));
  });

  it("renders persistent IR and drives play, pause, seek, stop, and RAF cleanup from one media clock", async () => {
    const playable = studio("available");
    playable.delivery_assets[0]!.duration_milliseconds = null;
    stubReads(playable, "ready");
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(async function(this: HTMLMediaElement) { Object.defineProperty(this, "paused", { configurable: true, value: false }); });
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const raf = vi.spyOn(window, "requestAnimationFrame").mockReturnValue(41);
    const cancelRaf = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);

    const view = renderStudio();
    expect(await screen.findByRole("heading", { name: "Orbital Glass" })).toBeInTheDocument();
    expect(screen.getByText("A very long atmospheric pad track name that must not widen the page")).toBeInTheDocument();
    expect(screen.getByText("Canvas 不可用时：Opening，Warm Pad 轨道，2 个片段。")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /只读 Arrangement 时间线/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    expect(await screen.findByRole("button", { name: "暂停" })).toBeInTheDocument();
    expect(play).toHaveBeenCalledOnce();
    expect(raf).toHaveBeenCalledOnce();

    const audio = document.querySelector("audio") as HTMLAudioElement;
    Object.defineProperty(audio, "currentTime", { configurable: true, writable: true, value: 2 });
    fireEvent.timeUpdate(audio);
    expect(screen.getByText("0:02 / 0:04")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("播放位置"), { target: { value: "4" } });
    expect(audio.currentTime).toBe(4);
    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    expect(pause).toHaveBeenCalled();
    expect(audio.currentTime).toBe(0);

    view.unmount();
    expect(cancelRaf).toHaveBeenCalledWith(41);
  });

  it("exposes only safe recovery actions for evicted, rehydrating, missing, and disconnected artifacts", async () => {
    let availability: "evicted" | "rehydrating" | "missing" = "evicted";
    let root: "ready" | "disconnected" = "ready";
    let rehydrateRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith(`/revisions/${REVISION_ID}/studio`)) return jsonResponse({ data: studio(availability) });
      if (path === `/api/v1/projects/${PROJECT_ID}`) return jsonResponse({ data: project(root) });
      if (path === `/api/v1/artifacts/${ARTIFACT_ID}/rehydrate` && init?.method === "POST") {
        rehydrateRequests += 1;
        availability = "rehydrating";
        return jsonResponse({ status: "succeeded", data: { thread_id: "rehydrate-thread", run_id: "44444444-4444-4444-8444-444444444444", job_id: "55555555-5555-4555-8555-555555555555", artifact_id: ARTIFACT_ID, phase: "waiting_worker", error_code: null, replayed: false } });
      }
      throw new Error(`unexpected request ${path}`);
    }));

    const first = renderStudio();
    fireEvent.click(await screen.findByRole("button", { name: "恢复 MP3" }));
    expect(await screen.findByText("恢复任务已进入持久队列")).toBeInTheDocument();
    expect(rehydrateRequests).toBe(1);
    first.unmount();

    availability = "rehydrating";
    const second = renderStudio();
    expect(await screen.findByText("正在重新生成 MP3，完成后刷新即可播放")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复 MP3" })).not.toBeInTheDocument();
    second.unmount();

    availability = "missing";
    const third = renderStudio();
    expect(await screen.findByText("恢复 MP3 所需的源文件缺失，请检查原始素材")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复 MP3" })).not.toBeInTheDocument();
    third.unmount();

    availability = "evicted";
    root = "disconnected";
    renderStudio();
    expect(await screen.findByText("作品存储位置暂不可用")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复 MP3" })).not.toBeInTheDocument();
  });

  it("renders empty, partial-success, and media-error states without inventing edit controls", async () => {
    const projection = studio("available");
    projection.bundle_id = null;
    projection.arrangement_ir.tracks = [];
    projection.arrangement_ir.sections = [];
    stubReads(projection, "ready");

    renderStudio();
    expect(await screen.findByText("作品已保存，导出尚未完整完成")).toBeInTheDocument();
    expect(screen.getByText("这个版本还没有音轨")).toBeInTheDocument();
    fireEvent.error(document.querySelector("audio") as HTMLAudioElement);
    expect(await screen.findByText("MP3 无法播放")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /静音|独奏|删除|移动/ })).not.toBeInTheDocument();
  });
});

function renderStudio() {
  window.history.replaceState({}, "", `/projects/${PROJECT_ID}/studio/${REVISION_ID}`);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><StudioPage projectId={PROJECT_ID} revisionId={REVISION_ID} /></QueryClientProvider>);
}

function stubReads(value: RevisionStudio, root: "ready" | "disconnected") {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith(`/revisions/${REVISION_ID}/studio`)) return jsonResponse({ data: value });
    if (path === `/api/v1/projects/${PROJECT_ID}`) return jsonResponse({ data: project(root) });
    throw new Error(`unexpected request ${path}`);
  }));
}

function studio(availability: "available" | "evicted" | "rehydrating" | "missing"): RevisionStudio {
  return {
    project_id: PROJECT_ID,
    revision_id: REVISION_ID,
    parent_revision_id: null,
    source_run_id: "66666666-6666-4666-8666-666666666666",
    reason_code: "generated",
    author_kind: "agent",
    created_by: "parent-graph",
    created_at: "2026-08-20T08:00:00Z",
    bundle_id: "77777777-7777-4777-8777-777777777777",
    delivery_assets: [{ artifact_id: ARTIFACT_ID, availability, quality_profile: "delivery-mp3.v1", media_type: "audio/mpeg", byte_size: 1024, duration_milliseconds: 8000 }],
    arrangement_ir: {
      schema_version: "arrangement-ir.v1",
      project_id: PROJECT_ID,
      ppq: 480,
      sample_rate: 48000,
      tempo_map: [{ tick: 0, bpm: 120 }],
      time_signature_map: [{ tick: 0, numerator: 4, denominator: 4 }],
      key_map: [], markers: [], provenance: [],
      sections: [{ section_id: "88888888-8888-4888-8888-888888888888", label: "Opening", start_tick: 0, end_tick: 3840, energy: 0.4, function: "establish" }],
      tracks: [{
        track_id: "99999999-9999-4999-8999-999999999999",
        name: "A very long atmospheric pad track name that must not widen the page",
        track_type: "instrument", role: "harmony", instrument_ref: "warm-pad.v1", gain_db: 0, pan: 0, mute: false, solo: false, locked_ranges: [],
        clips: [noteClip("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 0), noteClip("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", 1920)],
      }],
    },
  };
}

function noteClip(clipId: string, startTick: number): RevisionStudio["arrangement_ir"]["tracks"][number]["clips"][number] {
  return { clip_id: clipId, clip_type: "note", start_tick: startTick, duration_tick: 960, loop: false, gain_db: 0, pan: 0, fade_in_tick: 0, fade_out_tick: 0, notes: [] };
}

function project(storageRootStatus: "ready" | "disconnected") {
  return { project_id: PROJECT_ID, name: "Orbital Glass", status: "active", updated_at: "2026-08-20T08:00:00Z", active_branch_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", head_revision_id: REVISION_ID, revisions: [], runs: [], recoverable_run: null, storage_root_status: storageRootStatus };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
}

it('opens the returned Undo revision instead of pairing its ID with the previous score',async()=>{
  const restoredId='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';let restoredReads=0;
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=String(input);
    if(path.endsWith(`/revisions/${REVISION_ID}/studio`)){const value=studio('available');value.parent_revision_id=restoredId;return jsonResponse({data:value});}
    if(path.endsWith(`/revisions/${restoredId}/studio`)){restoredReads++;const value=studio('available');value.revision_id=restoredId;return jsonResponse({data:value});}
    if(path===`/api/v1/projects/${PROJECT_ID}`)return jsonResponse({data:project('ready')});
    if(path.endsWith('/undo')&&init?.method==='POST')return jsonResponse({data:{revision_id:restoredId}});
    if(path==='/api/v1/piano-capability')return jsonResponse({data:{available:false}});
    if(path==='/api/v1/sound-catalog')return jsonResponse({data:[]});
    throw new Error(path);
  }));
  renderStudio();fireEvent.click(await screen.findByRole('button',{name:'撤回已保存修改'}));
  await waitFor(()=>expect(restoredReads).toBe(1));
});

it.each(['arrangement-ir.v1','arrangement-ir.v2'] as const)('keeps library actions truthful for %s',async(schema)=>{
  const value=studio('available');
  if(schema==='arrangement-ir.v2')value.arrangement_ir={...value.arrangement_ir,schema_version:schema,
    render_profile:{schema_version:'render-profile.v1',engine_version:'motif-forge-audio-engine.v2',
      instrument_pack_id:'freepats:upright-kw-small',instrument_pack_version:'2019-07-03.motif1',
      manifest_sha256:'264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813'}};
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
    const path=String(input);
    if(path.endsWith(`/revisions/${REVISION_ID}/studio`))return jsonResponse({data:value});
    if(path===`/api/v1/projects/${PROJECT_ID}`)return jsonResponse({data:project('ready')});
    if(path==='/api/v1/sound-catalog')return jsonResponse({data:[{preset_id:'builtin:viola',style:'classical',instrument_family:'Viola',role:'harmony',low_midi:48,high_midi:84,reviewed:true,license_id:'builtin',attribution_required:false}]});
    if(path==='/api/v1/piano-capability')return jsonResponse({data:{available:false}});
    throw new Error(path);
  }));
  renderStudio();fireEvent.click(await screen.findByRole('tab',{name:'音色库'}));
  await screen.findByLabelText('本地审核音色库');
  if(schema==='arrangement-ir.v2'){
    expect(screen.queryByRole('button',{name:'用于所选轨道'})).not.toBeInTheDocument();
    expect(screen.getByText('当前版本使用已确认的钢琴音源，普通音色切换暂不支持。')).toBeInTheDocument();
  }else expect(screen.getByRole('button',{name:'用于所选轨道'})).toBeInTheDocument();
});
