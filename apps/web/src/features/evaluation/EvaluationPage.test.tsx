import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as api from "./evaluationApi";
import { EvaluationPage } from "./EvaluationPage";

describe("EvaluationPage", () => {
  it("renders measured, rejected, and unmeasured evidence separately", async () => {
    vi.spyOn(api, "loadEvaluationReport").mockResolvedValue({
      schema_version: "motif-forge-eval-report.v1",
      internal_case_count: 96,
      public_measured_case_count: 80,
      summary: {
        measured: { denominator: 80, passed: 80, failed: 0 },
        expected_reject: 13,
        not_measured: 3,
      },
      stage_inventory: { S7: { internal: 24, measured: 19, expected_reject: 3, not_measured: 2 } },
      current_run_usage: { provider_requests: 0, total_tokens: 0 },
      latency: { p50_ms: "<100", p95_ms: "<100" },
      not_measured_claims: ["perceptual audio quality"],
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={client}><EvaluationPage /></QueryClientProvider>);

    expect(await screen.findByText("96")).toBeInTheDocument();
    expect(screen.getByText("80 / 80")).toBeInTheDocument();
    expect(screen.getByText("Expected reject")).toBeInTheDocument();
    expect(screen.getByText("perceptual audio quality")).toBeInTheDocument();
  });
});
