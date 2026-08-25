import { afterEach, expect, it, vi } from "vitest";

import { readRevisionExport } from "./exportApi";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const REVISION_ID = "22222222-2222-4222-8222-222222222222";

afterEach(() => vi.unstubAllGlobals());

it("reads the generated Export projection route", async () => {
  const projection = { project_id: PROJECT_ID, revision_id: REVISION_ID, status: "partial" };
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ data: projection }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  expect(await readRevisionExport(PROJECT_ID, REVISION_ID)).toEqual(projection);
  expect(fetchMock).toHaveBeenCalledWith(
    `/api/v1/projects/${PROJECT_ID}/revisions/${REVISION_ID}/exports`, undefined,
  );
});
