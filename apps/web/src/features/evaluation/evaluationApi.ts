export interface EvaluationReport {
  schema_version: "motif-forge-eval-report.v1";
  internal_case_count: number;
  public_measured_case_count: number;
  summary: {
    measured: { denominator: number; passed: number; failed: number };
    expected_reject: number;
    not_measured: number;
  };
  stage_inventory: Record<
    string,
    { internal: number; measured: number; expected_reject: number; not_measured: number }
  >;
  current_run_usage: { provider_requests: number; total_tokens: number };
  latency: { p50_ms: string; p95_ms: string };
  not_measured_claims: string[];
}

export async function loadEvaluationReport(): Promise<EvaluationReport> {
  const response = await fetch("/evals/s7-report.v1.json", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("EVAL_REPORT_UNAVAILABLE");
  return response.json() as Promise<EvaluationReport>;
}
