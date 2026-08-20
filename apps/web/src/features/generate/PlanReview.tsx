import { FormEvent, useState } from "react";

import type { RunPlan } from "../../shared/openapi";

const STYLE_EVIDENCE = {
  synth_ambient: { pack: "style:synth-ambient:v1", strategy: "音色、密度与空间层次", source: "Motif Forge Ambient Strategy Notes" },
  minimal_electronic: { pack: "style:minimal-electronic:v1", strategy: "Groove、低频锁定与段落能量", source: "Motif Forge Minimal Electronic Strategy Notes" },
  classical_chamber: { pack: "style:classical-chamber:v1", strategy: "曲式、声部进行与可演奏音域", source: "Motif Forge Chamber Strategy Notes" },
  jazz_harmony_improvisation: { pack: "style:jazz-harmony-improvisation:v1", strategy: "Guide tones、voicing 与 swing phrase", source: "Motif Forge Jazz Strategy Notes" },
} as const;

export interface PlanDecision {
  actorId: string;
  assertion: string;
  decision: "approve" | "reject";
  note: string;
}

export function PlanReview({ plan, busy, onDecision }: { plan: RunPlan; busy: boolean; onDecision: (decision: PlanDecision) => void }) {
  const [actorId, setActorId] = useState("");
  const [assertion, setAssertion] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const composition = plan.plan;
  const styleEvidence = STYLE_EVIDENCE[composition.genre];

  function decide(event: FormEvent<HTMLFormElement>, decision: "approve" | "reject") {
    event.preventDefault();
    submitDecision(decision);
  }

  function submitDecision(decision: "approve" | "reject") {
    if (!actorId.trim()) setError("请填写审批人。");
    else if (assertion.trim().length < 16) setError("审批确认至少需要 16 个字符。");
    else {
      setError(null);
      onDecision({ actorId: actorId.trim(), assertion: assertion.trim(), decision, note: note.trim() });
    }
  }

  return (
    <article className="plan-review" aria-labelledby="plan-title">
      <header className="panel-heading">
        <div><p className="eyebrow">AGENT PLAN / HUMAN GATE</p><h2 id="plan-title">{plan.fallback_reason ? "Fallback Plan · 仍需人工审批" : "Composition Plan · 等待人工审批"}</h2></div>
        <div className="plan-tempo"><strong>{composition.bpm} BPM</strong><span>{composition.key.tonic} {composition.key.mode}</span><span>{composition.meter}</span></div>
      </header>
      <div className="plan-language-grid">
        <PlanFact label="和声" value={composition.harmonic_language} />
        <PlanFact label="节奏" value={composition.rhythmic_language} />
        <PlanFact label="织体" value={composition.texture} />
      </div>
      <section className="strategy-evidence" aria-label="风格策略依据">
        <div><span>STYLE PACK</span><strong>{styleEvidence.pack}</strong></div>
        <div><span>策略路径</span><strong>{styleEvidence.strategy}</strong></div>
        <div><span>策展来源</span><strong>{styleEvidence.source}</strong></div>
        <div><span>许可</span><strong>Project-authored · 已审核 · 允许作品集使用</strong></div>
        <p>来源文本只解释策略；音符合法性由确定性 Theory Engine 判断。</p>
      </section>
      <section className="plan-sections" aria-label="乐曲结构">
        {composition.sections.map((section) => (
          <article key={section.section_id}>
            <header><h3>{section.name}</h3><span>{section.start_bar + 1}–{section.end_bar} 小节</span></header>
            <p>{section.function}</p>
            <div className="energy-track" aria-hidden="true"><span style={{ width: `${Math.round(section.energy * 100)}%` }} /></div>
            <small>能量 {Math.round(section.energy * 100)}%</small>
          </article>
        ))}
      </section>
      <section className="plan-instruments" aria-labelledby="instrument-title">
        <h3 id="instrument-title">配器角色</h3>
        <div>{composition.instrumentation.map((instrument) => <span key={instrument.instrument_id}><strong>{instrument.name}</strong> · {instrument.role}</span>)}</div>
      </section>
      {composition.knowledge_references.length > 0 && (
        <section className="plan-references"><h3>规划依据</h3>{composition.knowledge_references.map((reference) => <p key={reference.reference_id}>{reference.summary}</p>)}</section>
      )}
      <form className="approval-form" onSubmit={(event) => decide(event, "approve")}>
        <div className="approval-grid">
          <label><span>审批人</span><input value={actorId} onChange={(event) => setActorId(event.target.value)} autoComplete="off" /></label>
          <label><span>审批确认</span><input value={assertion} onChange={(event) => setAssertion(event.target.value)} autoComplete="off" /></label>
          <label><span>审批备注（可选）</span><input value={note} onChange={(event) => setNote(event.target.value)} /></label>
        </div>
        {error && <p className="field-error" role="alert">{error}</p>}
        <div className="decision-row">
          <button className="primary-button" type="submit" disabled={busy}>批准并生成</button>
          <button className="danger-button" type="button" disabled={busy} onClick={() => submitDecision("reject")}>拒绝计划</button>
          <small>操作绑定当前 Plan 版本与内容标识；页面不保存审批确认文本。</small>
        </div>
      </form>
    </article>
  );
}

function PlanFact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><p>{value}</p></div>;
}
