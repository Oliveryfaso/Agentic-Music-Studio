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

export function PlanReview({ plan, busy, onDecision, reviewable = true }: { plan: RunPlan; busy: boolean; onDecision: (decision: PlanDecision) => void; reviewable?: boolean }) {
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
        <div><p className="eyebrow">COMPOSITION PLAN</p><h2 id="plan-title">{reviewable ? "先确认音乐的方向" : "这次创作的编曲计划"}</h2></div>
        <div className="plan-tempo"><strong>{composition.bpm} BPM</strong><span>{composition.key.tonic} {composition.key.mode}</span><span>{composition.meter}</span></div>
      </header>
      {plan.fallback_reason && <p className="plan-fallback" role="status">当前使用规则生成的备用计划（Fallback），不是模型生成结果。{reviewable ? "请确认它是否符合你的想法。" : "备用计划同样遵循人工审批规则。"}</p>}
      <div className="plan-language-grid">
        <PlanFact label="和声" value={composition.harmonic_language} />
        <PlanFact label="节奏" value={composition.rhythmic_language} />
        <PlanFact label="织体" value={composition.texture} />
      </div>
      <details className="plan-source-details"><summary>风格策略与来源依据</summary><section className="strategy-evidence" aria-label="风格策略依据">
        <div><span>STYLE PACK</span><strong>{styleEvidence.pack}</strong></div>
        <div><span>策略路径</span><strong>{styleEvidence.strategy}</strong></div>
        <div><span>策展来源</span><strong>{styleEvidence.source}</strong></div>
        <div><span>许可</span><strong>Project-authored · 已审核 · 允许作品集使用</strong></div>
        <p>来源文本只解释策略；音符合法性由确定性 Theory Engine 判断。</p>
      </section></details>
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
      {reviewable && <form className="approval-form" onSubmit={(event) => decide(event, "approve")}>
        <div className="approval-intro"><h3>方向合适，就开始生成</h3><p>确认后会生成两份可试听的候选；选定之前，不会替换作品的正式版本。</p></div>
        <div className="approval-grid">
          <label><span>审批人</span><input value={actorId} onChange={(event) => setActorId(event.target.value)} autoComplete="off" placeholder="你的名字或昵称" /></label>
          <label><span>审批确认</span><input value={assertion} onChange={(event) => setAssertion(event.target.value)} autoComplete="off" placeholder="描述你对这份计划的确认（至少 16 字符）" aria-describedby="approval-hint" /></label>
          <label><span>审批备注（可选）</span><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="补充你的判断" /></label>
        </div>
        {error && <p className="field-error" role="alert">{error}</p>}
        <div className="decision-row">
          <button className="primary-button" type="submit" disabled={busy}>批准并生成</button>
          <button className="danger-button" type="button" disabled={busy} onClick={() => submitDecision("reject")}>拒绝计划</button>
          <small id="approval-hint">确认当前计划后才会开始生成。你也可以拒绝，或在下方调整计划。</small>
        </div>
      </form>}
    </article>
  );
}

function PlanFact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><p>{value}</p></div>;
}
