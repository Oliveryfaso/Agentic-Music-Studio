import { afterEach, expect, it, vi } from "vitest";

import { readRunInspection } from "./inspectionApi";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
afterEach(() => vi.unstubAllGlobals());

it("reads the safe Run Inspector projection", async () => {
  const value = { run: { run_id: RUN_ID, status: "succeeded" } };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: value }), {
    status: 200, headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);

  expect(await readRunInspection(RUN_ID)).toEqual(value);
  expect(fetchMock).toHaveBeenCalledWith(`/api/v1/runs/${RUN_ID}/inspect`, undefined);
});
