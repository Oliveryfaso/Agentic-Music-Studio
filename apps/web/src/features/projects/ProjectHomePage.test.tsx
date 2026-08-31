import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectHomePage } from "./ProjectHomePage";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const RECOVERY_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const BRANCH_ID = "33333333-3333-4333-8333-333333333333";
const REVISION_ID = "44444444-4444-4444-8444-444444444444";
const RUN_ID = "55555555-5555-4555-8555-555555555555";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("Project Home", () => {
  it("covers loading, empty, create, cards, open, recovery, error, and retry", async () => {
    let releaseInitial: ((response: Response) => void) | undefined;
    const initial = new Promise<Response>((resolve) => { releaseInitial = resolve; });
    let listRequest = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects?limit=50" && init?.method !== "POST") {
        listRequest += 1;
        if (listRequest === 1) return initial;
        if (listRequest === 2 || listRequest === 4) return jsonResponse({ data: projects() });
        return jsonResponse(
          { detail: "Project catalog unavailable", error_code: "PROJECT_LIST_FAILED" },
          503,
        );
      }
      if (path === "/api/v1/projects" && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { name?: string };
        if (body.name !== "Orbital Glass") {
          return jsonResponse({ detail: "wrong project name", error_code: "INVALID_NAME" }, 422);
        }
        return jsonResponse({
          data: {
            project_id: PROJECT_ID,
            active_branch_id: BRANCH_ID,
            root_revision_id: REVISION_ID,
            content_hash: "not-used-by-the-home",
            replayed: false,
          },
        }, 201);
      }
      throw new Error(`unexpected request ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const first = renderHome();
    expect(screen.getByRole("status", { name: "正在载入项目" })).toBeInTheDocument();

    releaseInitial?.(jsonResponse({ data: [] }));
    expect(await screen.findByText("还没有作品")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("作品名称"), {
      target: { value: "Orbital Glass" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建作品" }));

    expect(await screen.findByRole("heading", { name: /Orbital Glass/ })).toBeInTheDocument();
    expect(screen.getByText("正在规划")).toBeInTheDocument();
    expect(screen.getByText(/A Very Long Portfolio Composition Name/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "打开 Orbital Glass 最新版本" }));
    expect(window.location.pathname).toBe(
      `/projects/${PROJECT_ID}/studio/${REVISION_ID}`,
    );

    window.history.replaceState({}, "", "/");
    fireEvent.click(screen.getByRole("button", { name: "恢复正在规划" }));
    expect(window.location.pathname).toBe(`/runs/${RUN_ID}`);

    first.unmount();
    window.history.replaceState({}, "", "/");
    renderHome();
    expect(await screen.findByText("Project catalog unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试载入" }));
    expect(await screen.findByRole("heading", { name: /Orbital Glass/ })).toBeInTheDocument();
  });

  it("sorts recent projects, limits the default view, and composes search with status", async () => {
    const values = Array.from({ length: 8 }, (_, index) => ({
      ...projects()[0],
      project_id: `00000000-0000-4000-8000-0000000000${String(index).padStart(2, "0")}`,
      name: `Project ${index + 1}`,
      status: index === 6 ? "archived" : "active",
      updated_at: `2026-08-${String(index + 1).padStart(2, "0")}T08:00:00Z`,
    }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ data: values })));
    renderHome();

    const list = await screen.findByLabelText("作品列表");
    expect(within(list).getAllByRole("heading", { level: 2 })).toHaveLength(6);
    expect(within(list).getAllByRole("heading", { level: 2 })[0]).toHaveTextContent("Project 8");
    expect(screen.queryByRole("heading", { name: "Project 1" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "全部项目与测试历史" }));
    expect(screen.getByRole("heading", { name: "Project 1" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜索作品"), { target: { value: "Project 7" } });
    fireEvent.change(screen.getByLabelText("作品状态"), { target: { value: "active" } });
    expect(screen.getByText("没有符合筛选条件的作品")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("作品状态"), { target: { value: "archived" } });
    expect(screen.getByRole("heading", { name: "Project 7" })).toBeInTheDocument();
  });
});

function renderHome() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProjectHomePage />
    </QueryClientProvider>,
  );
}

function projects() {
  return [
    {
      project_id: PROJECT_ID,
      name: "Orbital Glass",
      status: "active",
      updated_at: "2026-08-20T08:00:00Z",
      active_branch_id: BRANCH_ID,
      head_revision_id: REVISION_ID,
      latest_run: {
        run_id: "66666666-6666-4666-8666-666666666666",
        status: "succeeded",
        updated_at: "2026-08-20T08:00:00Z",
      },
      has_playable_revision: true,
    },
    {
      project_id: RECOVERY_PROJECT_ID,
      name: "A Very Long Portfolio Composition Name That Must Stay Inside Its Card Without Page Overflow",
      status: "active",
      updated_at: "2026-08-20T09:00:00Z",
      active_branch_id: "77777777-7777-4777-8777-777777777777",
      head_revision_id: "88888888-8888-4888-8888-888888888888",
      latest_run: {
        run_id: RUN_ID,
        status: "planning",
        updated_at: "2026-08-20T09:00:00Z",
      },
      has_playable_revision: false,
    },
  ];
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
