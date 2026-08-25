import { afterEach, describe, expect, it, vi } from "vitest";

import { readEvaluationReport } from "./evaluationApi";

afterEach(() => vi.unstubAllGlobals());

describe("readEvaluationReport", () => {
  it("loads the versioned public report without an API secret", async () => {
    const report = { schema_version: "motif-forge-eval-report.v1", internal_case_count: 96 };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(report)));
    vi.stubGlobal("fetch", fetchMock);

    await expect(readEvaluationReport()).resolves.toMatchObject(report);
    expect(fetchMock).toHaveBeenCalledWith("/evals/s7-report.v1.json", {
      headers: { Accept: "application/json" },
    });
  });
});
