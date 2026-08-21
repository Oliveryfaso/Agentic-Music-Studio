import { useState } from "react";

import { audioContentUrl } from "../../shared/api";
import type { AIRun } from "../../shared/openapi";

export interface CandidateDecision {
  decision: "select" | "reject";
  previewId?: string;
  candidateId?: string;
  candidateContentHash?: string;
  assertion: string;
  note: string;
}

export function CandidateCompare({
  run,
  busy,
  onSelect,
}: {
  run: AIRun;
  busy: boolean;
  onSelect: (decision: CandidateDecision) => void;
}) {
  const [playing, setPlaying] = useState<string | null>(null);
  const [assertion, setAssertion] = useState("");
  const [note, setNote] = useState("");
  const candidates = [...run.candidates].sort((left, right) =>
    left.label.localeCompare(right.label),
  );
  const recommendation = candidates.find(
    (candidate) => candidate.candidate_id === run.critique?.recommended_candidate_id,
  );
  const canDecide = assertion.trim().length >= 16 && !busy;

  return (
    <section className="candidate-compare" aria-labelledby="candidate-compare-title">
      <header className="candidate-compare-header">
        <div>
          <p className="eyebrow">HUMAN-IN-THE-LOOP</p>
          <h2 id="candidate-compare-title">比较候选 A / B</h2>
        </div>
        {recommendation && (
          <div className="critic-recommendation">
            <strong>Agent 建议：候选 {recommendation.label.toUpperCase()}</strong>
            <span>{run.critique?.rationale}</span>
          </div>
        )}
      </header>

      <div className="candidate-grid">
        {candidates.map((candidate) => {
          const assessment = run.critique?.assessments.find(
            (item) => item.candidate_id === candidate.candidate_id,
          );
          const evidence = run.critique?.evidence.filter(
            (item) => item.candidate_id === candidate.candidate_id,
          ) ?? [];
          const theoryErrors = evidence.filter(
            (item) => item.kind === "theory" && item.severity === "error",
          ).length;
          const active = playing === candidate.candidate_id;
          const playable = candidate.preview_availability === "available";
          return (
            <article className="candidate-card" key={candidate.candidate_id}>
              <div className="candidate-title-row">
                <h3>候选 {candidate.label.toUpperCase()}</h3>
                <span className={`repair-badge repair-${candidate.repair_status}`}>
                  {repairLabel(candidate.repair_status)}
                </span>
              </div>
              <dl className="candidate-facts">
                <div><dt>Critic 分数</dt><dd>{assessment?.score ?? "—"}</dd></div>
                <div><dt>风格</dt><dd>{run.plan?.plan.genre ?? "已编译"}</dd></div>
                <div><dt>结构</dt><dd>{run.plan?.plan.sections.length ?? "—"} 段</dd></div>
                <div><dt>Theory 阻断</dt><dd>{theoryErrors}</dd></div>
              </dl>
              {active ? (
                <audio
                  aria-label={`候选 ${candidate.label.toUpperCase()} 试听`}
                  controls
                  autoPlay
                  preload="metadata"
                  src={audioContentUrl(candidate.preview_artifact_id)}
                >浏览器不支持音频播放。</audio>
              ) : (
                <button
                  className="secondary-inline"
                  type="button"
                  disabled={!playable}
                  onClick={() => setPlaying(candidate.candidate_id)}
                >{playable
                  ? `试听候选 ${candidate.label.toUpperCase()}`
                  : previewAvailabilityLabel(candidate.preview_availability)}</button>
              )}
              <button
                className="primary-button"
                type="button"
                disabled={!canDecide || !playable}
                onClick={() => onSelect({
                  decision: "select",
                  previewId: candidate.preview_id,
                  candidateId: candidate.candidate_id,
                  candidateContentHash: candidate.candidate_content_hash,
                  assertion: assertion.trim(),
                  note: note.trim(),
                })}
              >选择候选 {candidate.label.toUpperCase()}</button>
            </article>
          );
        })}
      </div>

      <div className="candidate-decision-form">
        <label>选择确认
          <textarea
            value={assertion}
            onChange={(event) => setAssertion(event.target.value)}
            placeholder="说明你已比较两个权威 Preview（至少 16 个字符）"
          />
        </label>
        <label>备注（可选）
          <input value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
        <button
          className="danger-button"
          type="button"
          disabled={!canDecide}
          onClick={() => onSelect({
            decision: "reject", assertion: assertion.trim(), note: note.trim(),
          })}
        >拒绝两个候选</button>
      </div>
    </section>
  );
}

function repairLabel(value: AIRun["candidates"][number]["repair_status"]): string {
  return ({
    not_requested: "未修复",
    improved: "已改善",
    non_improving: "修复未采用",
  })[value];
}

function previewAvailabilityLabel(
  value: AIRun["candidates"][number]["preview_availability"],
): string {
  return ({
    available: "可试听",
    evicted: "Preview 已回收，可恢复",
    rehydrating: "Preview 恢复中",
    missing: "Preview 不可用",
  })[value];
}
