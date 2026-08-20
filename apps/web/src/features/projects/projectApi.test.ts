import { afterEach, describe, expect, it, vi } from "vitest";

import { listProjects, readProject } from "./projectApi";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const BRANCH_ID = "22222222-2222-4222-8222-222222222222";
const REVISION_ID = "33333333-3333-4333-8333-333333333333";

afterEach(() => vi.unstubAllGlobals());

describe("generated Project API client", () => {
  it("returns generated Project summaries and workspace data", async () => {
    const summary = {
      project_id: PROJECT_ID,
      name: "Orbital Glass",
      status: "active",
      updated_at: "2026-08-20T00:00:00Z",
      active_branch_id: BRANCH_ID,
      head_revision_id: REVISION_ID,
      latest_run: null,
      has_playable_revision: true,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: [summary] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        data: {
          ...summary,
          revisions: [],
          runs: [],
          recoverable_run: null,
          storage_root_status: "ready",
        },
      })));
    vi.stubGlobal("fetch", fetchMock);

    const projects = await listProjects();
    const workspace = await readProject(PROJECT_ID);

    expect(projects[0]?.head_revision_id).toBe(REVISION_ID);
    expect(workspace.storage_root_status).toBe("ready");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/v1/projects?limit=50",
      `/api/v1/projects/${PROJECT_ID}`,
    ]);
  });
});
