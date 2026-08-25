import { useQuery } from "@tanstack/react-query";

import { StatusBanner } from "../../app/StatusBanner";
import { readEvaluationReport } from "./evaluationApi";

export function EvaluationPage() {
  const query = useQuery({ queryKey: ["s7-evaluation"], queryFn: readEvaluationReport });

  if (query.isPending) {
    return <section className="evidence-page"><p className="eyebrow">EVIDENCE</p><h1>读取 Eval 报告…</h1></section>;
  }
  if (query.isError) {
    return <section className="evidence-page"><StatusBanner tone="danger" message="Eval 报告不可用" detail="请先运行 npm run eval:s7 生成版本化报告。" /></section>;
  }

  const report = query.data;
  return (
    <section className="evidence-page" aria-labelledby="evaluation-title">
      <header className="portfolio-hero">
        <div>
          <p className="eyebrow">S7 / EVALUATION</p>
          <h1 id="evaluation-title">可审计的 Agent 证据，不包装成虚假的满分。</h1>
          <p>内部案例、公开 measured 分母、预期拒绝和未测声明分别统计。</p>
        </div>
        <span className="evidence-version">{report.schema_version}</span>
      </header>

      <div className="evidence-metrics">
        <Metric label="Internal cases" value={String(report.internal_case_count)} />
        <Metric label="Measured pass" value={`${report.summary.measured.passed} / ${report.summary.measured.denominator}`} />
        <Metric label="Expected reject" value={String(report.summary.expected_reject)} />
        <Metric label="Not measured" value={String(report.summary.not_measured)} />
      </div>

      <div className="evidence-grid">
        <section className="portfolio-card">
          <p className="eyebrow">STAGE INVENTORY</p>
          <h2>S1–S7</h2>
          <ol className="stage-ledger">
            {Object.entries(report.stage_inventory).map(([stage, values]) => (
              <li key={stage}><strong>{stage}</strong><span>{values.internal} internal · {values.measured} measured</span></li>
            ))}
          </ol>
        </section>
        <section className="portfolio-card">
          <p className="eyebrow">BOUNDARIES</p>
          <h2>明确没有测量</h2>
          <ul className="boundary-list">
            {report.not_measured_claims.map((claim) => <li key={claim}>{claim}</li>)}
          </ul>
          <p className="evidence-footnote">当前报告生成：{report.current_run_usage.provider_requests} provider requests / {report.current_run_usage.total_tokens} tokens。聚焦测试延迟 P50 {report.latency.p50_ms}、P95 {report.latency.p95_ms}。</p>
        </section>
      </div>
      <section className="portfolio-architecture evaluation-provenance">
        <div><p className="eyebrow">HISTORICAL LIVE ACCEPTANCE</p><h2>{report.historical_live_acceptance.stage} 的一次有界付费证据</h2></div>
        <p>{report.historical_live_acceptance.evidence}（最多 {report.historical_live_acceptance.bounded_provider_requests} 次 provider request）；它不计入本轮 0/0 用量。</p>
      </section>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <article><span>{label}</span><strong>{value}</strong></article>;
}
