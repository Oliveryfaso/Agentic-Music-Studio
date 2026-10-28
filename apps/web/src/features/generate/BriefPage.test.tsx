import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BriefPage } from "./BriefPage";
import {NavigationGuard} from '../../app/NavigationGuard';

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const BRANCH_ID = "22222222-2222-4222-8222-222222222222";
const REVISION_ID = "33333333-3333-4333-8333-333333333333";
const RUN_ID = "44444444-4444-4444-8444-444444444444";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("New Composition Brief", () => {
  it("protects entered ideas when following the contextual settings link",async()=>{
    window.history.replaceState({},"",`/projects/${PROJECT_ID}/new-composition`);
    vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).includes('model-settings')?jsonResponse({data:{state:'not_configured',error_code:null}}):jsonResponse({data:projectWorkspace()})));
    const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
    render(<QueryClientProvider client={client}><NavigationGuard><BriefPage projectId={PROJECT_ID}/></NavigationGuard></QueryClientProvider>);
    await screen.findByRole('heading',{name:'新建编曲'});
    fireEvent.change(screen.getByLabelText('用途'),{target:{value:'An idea to keep'}});
    fireEvent.click(screen.getByRole('link',{name:'配置 API Key'}));
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByLabelText('用途')).toHaveValue('An idea to keep');
    expect(window.location.pathname).toBe(`/projects/${PROJECT_ID}/new-composition`);
  });
  it.each(["classical_chamber", "jazz_harmony_improvisation"])("submits focused %s while keeping invalid instrumental input local", async (selectedStyle) => {
    let createRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/model-settings") return jsonResponse({data:{state:"configured",error_code:null}});
      if (path === `/api/v1/projects/${PROJECT_ID}`) {
        return jsonResponse({ data: projectWorkspace() });
      }
      if (path === `/api/v1/projects/${PROJECT_ID}/ai-runs` && init?.method === "POST") {
        createRequests += 1;
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        const brief = body.brief as Record<string, unknown>;
        if (
          body.branch_id !== BRANCH_ID ||
          body.base_revision_id !== REVISION_ID ||
          body.max_model_requests !== 1 ||
          brief.schema_version !== "composition-brief.v1" ||
          brief.style !== selectedStyle ||
          brief.purpose !== "Instrumental background for a science-fiction puzzle" ||
          !Array.isArray(brief.moods) ||
          brief.moods.join(",") !== "weightless,curious"
        ) {
          return jsonResponse({ detail: "invalid Brief payload", error_code: "BRIEF_INVALID" }, 422);
        }
        return jsonResponse({ data: runData("queued") }, 202);
      }
      throw new Error(`unexpected request ${path}`);
    }));

    renderPage();
    expect(await screen.findByRole("heading", { name: "新建编曲" })).toBeInTheDocument();
    const strategy = screen.getByLabelText("音乐策略");
    expect(Array.from(strategy.querySelectorAll("option")).map((option) => option.textContent)).toEqual([
      "Classical Chamber",
      "Jazz Harmony & Improvisation",
    ]);

    expect(strategy).toHaveValue("classical_chamber");
    fillBrief("需要人声演唱的科幻背景");
    fireEvent.click(screen.getByRole("button", { name: "提交 Brief 并规划" }));
    expect(await screen.findByText("首版只支持纯器乐，请移除人声或演唱要求。")).toBeInTheDocument();
    expect(createRequests).toBe(0);

    fireEvent.change(screen.getByLabelText("用途"), {
      target: { value: "Instrumental background for a science-fiction puzzle" },
    });
    if (selectedStyle === "jazz_harmony_improvisation") {
      fireEvent.change(strategy, { target: { value: selectedStyle } });
    }
    fireEvent.click(screen.getByRole("button", { name: "提交 Brief 并规划" }));

    await screen.findByText("Run 已进入持久队列");
    expect(createRequests).toBe(1);
    expect(window.location.pathname).toBe(`/runs/${RUN_ID}`);
  });

  it("keeps core intent visible and preserves advanced values through disclosure and validation", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/model-settings") return jsonResponse({data:{state:"configured",error_code:null}});
      if (String(input) === `/api/v1/projects/${PROJECT_ID}`) return jsonResponse({ data: projectWorkspace() });
      throw new Error(`unexpected request ${String(input)}`);
    }));
    renderPage();

    expect(await screen.findByLabelText("作品标题")).toBeVisible();
    expect(screen.getByLabelText("音乐策略")).toBeVisible();
    expect(screen.getByLabelText("用途")).toBeVisible();
    expect(screen.getByLabelText("情绪")).toBeVisible();
    expect(screen.getByLabelText("目标时长（秒）")).toBeVisible();
    await waitFor(()=>expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled());
    const advanced = screen.getByText("高级编曲约束").closest("details")!;
    expect(advanced).not.toHaveAttribute("open");

    fireEvent.click(screen.getByText("高级编曲约束"));
    fireEvent.change(screen.getByLabelText("目标 BPM"), { target: { value: "999" } });
    fireEvent.click(screen.getByText("高级编曲约束"));
    fireEvent.click(screen.getByText("高级编曲约束"));
    expect(screen.getByLabelText("目标 BPM")).toHaveValue(999);
    fireEvent.click(screen.getByText("高级编曲约束"));

    fireEvent.change(screen.getByLabelText("作品标题"), { target: { value: "Orbital Glass" } });
    fireEvent.change(screen.getByLabelText("用途"), { target: { value: "Instrumental score" } });
    fireEvent.change(screen.getByLabelText("情绪"), { target: { value: "weightless" } });
    fireEvent.click(screen.getByRole("button", { name: "提交 Brief 并规划" }));
    expect(await screen.findByText("BPM 需在 40–220 之间。")).toBeInTheDocument();
    expect(advanced).toHaveAttribute("open");
    expect(screen.getByLabelText("目标 BPM")).toHaveFocus();
  });
});

it("offers an explicit free deterministic plan without a Key or connection test",async()=>{
  let creates=0;
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(String(input)==="/api/v1/model-settings")return jsonResponse({data:{state:"not_configured",error_code:null}});
    if(init?.method==="POST"){creates++;return jsonResponse({data:runData("queued")},202);}
    return jsonResponse({data:projectWorkspace()});
  });
  vi.stubGlobal("fetch",fetcher);renderPage();
  await screen.findByLabelText("作品标题");
  expect(await screen.findByText("未启用模型 · 可使用免费模板")).toBeInTheDocument();
  expect(screen.getByRole("link",{name:"配置 API Key"})).toHaveAttribute("href","/settings");
  const button=screen.getByRole("button",{name:"使用免费模板规划"});expect(button).toBeEnabled();
  expect(screen.queryByText(/描述将发送至 DeepSeek/)).not.toBeInTheDocument();expect(creates).toBe(0);
  fillBrief("Instrumental background");fireEvent.click(button);await screen.findByText("Run 已进入持久队列");
  expect(creates).toBe(1);expect(window.location.pathname).toBe(`/runs/${RUN_ID}`);
  expect(fetcher.mock.calls.every(([url])=>!String(url).includes("/model-settings/check"))).toBe(true);
});

it("distinguishes configuration loading from an actual submission",async()=>{
  let release!:(value:Response)=>void;
  const pending=new Promise<Response>(resolve=>{release=resolve;});
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>String(input)==="/api/v1/model-settings"?pending:jsonResponse({data:projectWorkspace()})));
  renderPage();await screen.findByLabelText("作品标题");
  expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeDisabled();
  expect(screen.queryByText("提交中…")).not.toBeInTheDocument();
  release(jsonResponse({data:{state:"configured",error_code:null}}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled());
});

it("reuses an unacknowledged request identity and blocks changing its music payload",async()=>{
  const sent:{key:string|null;body:string}[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(String(input)==="/api/v1/model-settings")return jsonResponse({data:{state:"configured",error_code:null}});
    if(init?.method==="POST"){
      sent.push({key:new Headers(init.headers).get("Idempotency-Key"),body:String(init.body)});
      if(sent.length===1)throw new Error("response lost after mock enqueue");
      return jsonResponse({data:runData("queued")},202);
    }
    return jsonResponse({data:projectWorkspace()});
  }));
  renderPage();await screen.findByLabelText("作品标题");
  await waitFor(()=>expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled());
  fillBrief("Original first idea");fireEvent.click(screen.getByRole("button",{name:"提交 Brief 并规划"}));await screen.findByText("Brief 提交失败");
  fireEvent.change(screen.getByLabelText("用途"),{target:{value:"Different idea"}});
  fireEvent.click(screen.getByRole("button",{name:"提交 Brief 并规划"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled());
  expect(sent).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("用途"),{target:{value:"Original first idea"}});
  fireEvent.click(screen.getByRole("button",{name:"提交 Brief 并规划"}));await screen.findByText("Run 已进入持久队列");
  expect(sent).toHaveLength(2);expect(sent[0]?.key).toBeTruthy();expect(sent[1]).toEqual(sent[0]);
});

it("lets a definitive validation rejection be corrected as a new request",async()=>{
  const sent:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(String(input)==="/api/v1/model-settings")return jsonResponse({data:{state:"configured",error_code:null}});
    if(init?.method==="POST"){
      sent.push(new Headers(init.headers).get("Idempotency-Key")!);
      return sent.length===1?jsonResponse({detail:"请修改创作约束",error_code:"BRIEF_INVALID"},422):jsonResponse({data:runData("queued")},202);
    }
    return jsonResponse({data:projectWorkspace()});
  }));
  renderPage();await screen.findByLabelText("作品标题");await waitFor(()=>expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled());
  fillBrief("First idea");fireEvent.click(screen.getByRole("button",{name:"提交 Brief 并规划"}));await screen.findByText("Brief 提交失败");
  fireEvent.change(screen.getByLabelText("用途"),{target:{value:"Corrected idea"}});
  fireEvent.click(screen.getByRole("button",{name:"提交 Brief 并规划"}));await screen.findByText("Run 已进入持久队列");
  expect(sent).toHaveLength(2);expect(sent[1]).not.toBe(sent[0]);
});

it("does not navigate back when a submission succeeds after leaving its page",async()=>{
  let release!:(response:Response)=>void,parsed=false,sent=0;
  const response=new Promise<Response>(resolve=>{release=resolve;});
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(String(input)==="/api/v1/model-settings")return jsonResponse({data:{state:"configured",error_code:null}});
    if(init?.method==="POST"){sent++;return response;}
    return jsonResponse({data:projectWorkspace()});
  }));
  const view=renderPage();await screen.findByLabelText("作品标题");await waitFor(()=>expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled());
  fillBrief("First idea");fireEvent.click(screen.getByRole("button",{name:"提交 Brief 并规划"}));await waitFor(()=>expect(sent).toBe(1));
  view.unmount();window.history.replaceState({},"","/settings");
  release({ok:true,json:async()=>{parsed=true;return {data:runData("queued")};}} as Response);
  await waitFor(()=>expect(parsed).toBe(true));expect(window.location.pathname).toBe("/settings");
});

it("recovers a configuration read failure without losing input and does not auto retry generation",async()=>{
  let ready=false,creates=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(String(input)==="/api/v1/model-settings")return ready?jsonResponse({data:{state:"configured",error_code:null}}):jsonResponse({detail:"private mock detail"},503);
    if(init?.method==="POST"){creates++;return jsonResponse({detail:"规划暂不可用",error_code:"PLANNING_UNAVAILABLE"},503);}
    return jsonResponse({data:projectWorkspace()});
  }));
  renderPage();await screen.findByText("无法读取模型配置");
  expect(screen.queryByText("private mock detail")).not.toBeInTheDocument();
  fillBrief("Keep this first idea");
  expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeDisabled();
  ready=true;fireEvent.click(screen.getByRole("button",{name:"刷新模型配置"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled());
  expect(screen.getByLabelText("用途")).toHaveValue("Keep this first idea");
  fireEvent.click(screen.getByRole("button",{name:"提交 Brief 并规划"}));
  await screen.findByText("Brief 提交失败");
  expect(screen.getByLabelText("用途")).toHaveValue("Keep this first idea");expect(creates).toBe(1);
  expect(screen.getByRole("button",{name:"提交 Brief 并规划"})).toBeEnabled();
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BriefPage projectId={PROJECT_ID} />
    </QueryClientProvider>,
  );
}

function fillBrief(purpose: string) {
  fireEvent.change(screen.getByLabelText("作品标题"), { target: { value: "Orbital Glass" } });
  fireEvent.change(screen.getByLabelText("用途"), { target: { value: purpose } });
  fireEvent.change(screen.getByLabelText("情绪"), { target: { value: "weightless, curious" } });
  fireEvent.change(screen.getByLabelText("偏好乐器"), { target: { value: "warm pad, soft pulse" } });
  fireEvent.change(screen.getByLabelText("目标 BPM"), { target: { value: "72" } });
  fireEvent.change(screen.getByLabelText("目标调性"), { target: { value: "D dorian" } });
}

function projectWorkspace() {
  return {
    project_id: PROJECT_ID,
    name: "Orbital Glass",
    status: "active",
    updated_at: "2026-08-20T08:00:00Z",
    active_branch_id: BRANCH_ID,
    head_revision_id: REVISION_ID,
    revisions: [],
    runs: [],
    recoverable_run: null,
    storage_root_status: "ready",
  };
}

function runData(status: "queued") {
  return {
    run_id: RUN_ID,
    parent_run_id: null,
    project_id: PROJECT_ID,
    branch_id: BRANCH_ID,
    base_revision_id: REVISION_ID,
    thread_id: "generate-brief-test",
    status,
    version: 0,
    pending_action: null,
    pending_plan_id: null,
    pending_plan_hash: null,
    submitted_model_requests: 0,
    max_model_requests: 1,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    model_usage_status: "unknown",
    cost_status: "unknown",
    cost_amount_microusd: null,
    cost_pricing_version: null,
    revision_id: null,
    bundle_id: null,
    fallback_reason: null,
    error_code: null,
    plan: null,
    progress: {
      phase: status,
      completed_export_steps: [],
      total_export_steps: 7,
      latest_event_sequence: 1,
      error_code: null,
    },
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
