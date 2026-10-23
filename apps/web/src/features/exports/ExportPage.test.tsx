import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";

import type { RevisionExportProjection } from "../../shared/openapi";
import { ExportPage } from "./ExportPage";
import { useLocationSearch } from "../../app/NavigationGuard";
import { navigateHref } from "../../app/routes";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const REVISION_ID = "22222222-2222-4222-8222-222222222222";
const RUN_ID = "33333333-3333-4333-8333-333333333333";
const MASTER_ID = "44444444-4444-4444-8444-444444444444";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });

it("presents compact delivery rows with exact-version return and no render on entry", async () => {
  stubProjection(projection("ready")); renderPage();
  expect(await screen.findByRole("heading", {name:"导出"})).toBeInTheDocument();
  expect(screen.getByRole("list", {name:"导出文件"})).toBeInTheDocument();
  expect(screen.getByRole("link", {name:"返回 Studio"})).toHaveAttribute("href",`/projects/${PROJECT_ID}/studio/${REVISION_ID}`);
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>!init?.method||init.method==="GET")).toBe(true);
});

it("renders the seven authoritative steps and delivery links", async () => {
  stubProjection(projection("ready"));
  renderPage();

  expect(await screen.findAllByTestId("export-step")).toHaveLength(7);
  expect(screen.getByRole("link", { name: /Master WAV/ })).toHaveAttribute(
    "href", `/api/v1/audio-artifacts/${MASTER_ID}/content`,
  );
  expect(screen.getByRole("link", { name: "查看执行记录" })).toHaveAttribute(
    "href", `/runs/${RUN_ID}/inspect`,
  );
});

it("keeps safe files visible while labeling partial failure", async () => {
  const value = projection("failed");
  value.steps[1]!.status = "failed";
  value.steps[1]!.error_code = "RENDER_FAILED";
  stubProjection(value);
  renderPage();

  expect(await screen.findByText("导出部分完成")).toBeInTheDocument();
  expect(screen.getByText("RENDER_FAILED")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Master WAV/ })).toBeInTheDocument();
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExportPage projectId={PROJECT_ID} revisionId={REVISION_ID} />
    </QueryClientProvider>,
  );
}

function stubProjection(value: RevisionExportProjection) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: value }), {
    status: 200, headers: { "Content-Type": "application/json" },
  })));
}

function projection(status: "ready" | "failed"): RevisionExportProjection {
  return {
    project_id: PROJECT_ID,
    revision_id: REVISION_ID,
    source_run_id: RUN_ID,
    status,
    error_code: status === "failed" ? "EXPORT_PARTIAL_FAILURE" : null,
    bundle: status === "ready" ? {
      bundle_id: "55555555-5555-4555-8555-555555555555",
      project_id: PROJECT_ID, revision_id: REVISION_ID, availability: "available",
      content_hash: "a".repeat(64), byte_size: 2048, file_count: 13,
    } : null,
    steps: ["master", "stem:pad", "stem:melody", "stem:bass", "stem:rhythm", "mp3", "bundle"].map((step, index) => ({
      step, job_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      status: "succeeded", artifact_id: null, error_code: null,
    })),
    files: [{
      file_id: `audio:${MASTER_ID}`, filename: "master.wav", category: "master",
      media_type: "audio/wav", byte_size: 1024, availability: "available",
      checksum: "b".repeat(64),
      content_url: `/api/v1/audio-artifacts/${MASTER_ID}/content`, artifact_id: MASTER_ID,
    }],
  };
}

it("starts only the requested files, reads its plan and cancels that finite request", async () => {
  const { fireEvent, waitFor } = await import("@testing-library/react");
  const posts: Array<{ path: string; body: unknown }> = [];
  const planHash = "c".repeat(64);
  const thread = "export-" + "d".repeat(32);
  let started = false;
  let cancelled = false;
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push({ path, body: init.body ? JSON.parse(String(init.body)) : null });
      if (path.endsWith("/cancel")) cancelled = true;
      else started = true;
      return new Response(JSON.stringify({ data: { thread_id: thread, phase: cancelled ? "cancelled" : "waiting_export_worker", plan_hash: planHash } }));
    }
    const value = projection("ready");
    if (started) {
      value.status = cancelled ? "cancelled" : "partial";
      value.export_thread_id = thread;
      value.plan_hash = planHash;
      value.steps = ["master", "bundle"].map((step) => ({ step, job_id: MASTER_ID, status: "queued", artifact_id: null }));
      value.files = [];
    }
    return new Response(JSON.stringify({ data: value }));
  }));
  renderPage();
  const mp3 = await screen.findByRole("checkbox", { name: "包含试听 MP3" });
  fireEvent.click(mp3);
  fireEvent.click(screen.getByRole("button", { name: "重新导出" }));
  await waitFor(() => expect(screen.getAllByTestId("export-step")).toHaveLength(2));
  expect(posts[0]?.body).toEqual({ include_mp3: false, include_all_stems: false });
  expect(window.location.search).toContain(planHash);
  fireEvent.click(screen.getByRole("button", { name: "取消导出" }));
  await screen.findByText("导出已取消");
  expect(posts[1]?.path).toContain(`/export-runs/${thread}/cancel`);
  window.history.replaceState(null, "", "/");
});

it('never exposes the old plan cancellation in a committed new-plan view',async()=>{
 const first='a'.repeat(64),second='b'.repeat(64),firstThread='export-'+ 'a'.repeat(32),secondThread='export-'+ 'b'.repeat(32);
 const path=`/projects/${PROJECT_ID}/exports/${REVISION_ID}`;let release:((value:Response)=>void)|undefined;const posts:string[]=[];let bLoaded=false;
 const bFile='/api/v1/audio-artifacts/88888888-8888-4888-8888-888888888888/content';
 function value(plan:string,thread:string){const result={...projection('ready'),status:'partial' as const,plan_hash:plan,export_thread_id:thread};if(plan===second)result.files[0]!.content_url=bFile;return result;}
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=String(input);if(init?.method==='POST'){posts.push(url);return new Response(JSON.stringify({data:{thread_id:secondThread,phase:'cancelled',plan_hash:second}}));}
  if(url.includes(`plan_hash=${second}`))return bLoaded?new Response(JSON.stringify({data:value(second,secondThread)})):await new Promise<Response>(resolve=>{release=resolve;});
  return new Response(JSON.stringify({data:value(first,firstThread)}));
 }));
 const commits:Array<{enabledCancel:boolean;oldDownload:boolean}>=[];
 function Probe(){const search=useLocationSearch();useLayoutEffect(()=>{if(new URLSearchParams(search).get('export_plan')!==second||bLoaded)return;
  const cancel=screen.queryByRole('button',{name:'取消导出'});commits.push({enabledCancel:Boolean(cancel&&!(cancel as HTMLButtonElement).disabled),oldDownload:Boolean(screen.queryByRole('link',{name:/下载 Master WAV/}))});
 },[search]);return null;}
 window.history.replaceState({},'',path+'?export_plan='+first);
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});render(<QueryClientProvider client={client}><ExportPage projectId={PROJECT_ID} revisionId={REVISION_ID}/><Probe/></QueryClientProvider>);
 await screen.findByRole('button',{name:'取消导出'});act(()=>navigateHref(path+'?export_plan='+second));
 await waitFor(()=>expect(release).toBeDefined());expect(commits.length).toBeGreaterThan(0);expect(commits.every(c=>!c.enabledCancel&&!c.oldDownload)).toBe(true);
 expect(posts).toHaveLength(0);await act(async()=>{bLoaded=true;release!(new Response(JSON.stringify({data:value(second,secondThread)})));});
 await waitFor(()=>expect(screen.getByRole('link',{name:/下载 Master WAV/})).toHaveAttribute('href',bFile));
 act(()=>window.history.back());await waitFor(()=>expect(window.location.search).toContain(first));await waitFor(()=>expect(screen.getByRole('link',{name:/下载 Master WAV/})).toHaveAttribute('href',`/api/v1/audio-artifacts/${MASTER_ID}/content`));
 act(()=>window.history.forward());await waitFor(()=>expect(window.location.search).toContain(second));await waitFor(()=>expect(screen.getByRole('link',{name:/下载 Master WAV/})).toHaveAttribute('href',bFile));expect(posts).toHaveLength(0);
 fireEvent.click(await screen.findByRole('button',{name:'取消导出'}));await waitFor(()=>expect(posts).toHaveLength(1));
 expect(posts[0]).toContain('/export-runs/'+secondThread+'/cancel');expect(posts[0]).not.toContain(firstThread);
});

it('does not keep B busy or apply A cancellation feedback after changing plans',async()=>{
 const first='a'.repeat(64),second='b'.repeat(64),firstThread='export-'+ 'a'.repeat(32),secondThread='export-'+ 'b'.repeat(32);
 const path=`/projects/${PROJECT_ID}/exports/${REVISION_ID}`;let release:((value:Response)=>void)|undefined;const posts:string[]=[];
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=String(input);if(init?.method==='POST'){posts.push(url);return await new Promise<Response>(resolve=>{release=resolve;});}
  const plan=url.includes(`plan_hash=${second}`)?second:first;
  return new Response(JSON.stringify({data:{...projection('ready'),status:'partial',plan_hash:plan,export_thread_id:plan===first?firstThread:secondThread}}));
 }));
 window.history.replaceState({},'',path+'?export_plan='+first);renderPage();fireEvent.click(await screen.findByRole('button',{name:'取消导出'}));
 await waitFor(()=>expect(release).toBeDefined());act(()=>navigateHref(path+'?export_plan='+second));
 await waitFor(()=>expect(screen.getByRole('button',{name:'取消导出'})).toBeEnabled());
 const location=window.location.href;await act(async()=>release!(new Response(JSON.stringify({data:{thread_id:firstThread,phase:'cancelled',plan_hash:first}}))));
 expect(window.location.href).toBe(location);expect(screen.getByRole('button',{name:'取消导出'})).toBeEnabled();expect(posts).toHaveLength(1);expect(posts[0]).toContain(firstThread);
 expect(screen.queryByText('导出已取消')).not.toBeInTheDocument();
});

it('does not publish a delayed export result into the next page URL',async()=>{
 const first='a'.repeat(64),newPlan='c'.repeat(64);let release:((value:Response)=>void)|undefined;let posts=0;
 vi.stubGlobal('fetch',vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>{
  if(init?.method==='POST'){posts++;return await new Promise<Response>(resolve=>{release=resolve;});}
  return new Response(JSON.stringify({data:{...projection('ready'),plan_hash:first}}));
 }));
 window.history.replaceState({},'',`/projects/${PROJECT_ID}/exports/${REVISION_ID}?export_plan=${first}`);
 const view=renderPage();fireEvent.click(await screen.findByRole('button',{name:'重新导出'}));await waitFor(()=>expect(release).toBeDefined());view.unmount();
 window.history.replaceState({},'',`/projects/${PROJECT_ID}/studio/${REVISION_ID}`);const location=window.location.href;
 await act(async()=>release!(new Response(JSON.stringify({data:{thread_id:'export-'+ 'c'.repeat(32),phase:'waiting_export_worker',plan_hash:newPlan}}))));
 expect(window.location.href).toBe(location);expect(posts).toBe(1);
});

it('withholds all export actions when an explicit plan response has another identity',async()=>{
 const first='a'.repeat(64),second='b'.repeat(64);const writes:string[]=[];let reads=0;
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  if(init?.method==='POST')writes.push(String(input));else reads++;
  return new Response(JSON.stringify({data:{...projection('ready'),status:'partial',plan_hash:first,export_thread_id:'export-'+ 'a'.repeat(32)}}));
 }));
 window.history.replaceState({},'',`/projects/${PROJECT_ID}/exports/${REVISION_ID}?export_plan=${second}`);renderPage();
 await waitFor(()=>expect(screen.queryByRole('heading',{name:'正在整理交付文件'})).not.toBeInTheDocument());
 expect(screen.queryByRole('button',{name:'取消导出'})).not.toBeInTheDocument();expect(screen.queryByRole('link',{name:/下载/})).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:/重新导出|生成导出文件|重试请求/})).not.toBeInTheDocument();expect(writes).toHaveLength(0);
 fireEvent.click(screen.getByRole('button',{name:'重新读取导出'}));await waitFor(()=>expect(reads).toBe(2));expect(writes).toHaveLength(0);
});
