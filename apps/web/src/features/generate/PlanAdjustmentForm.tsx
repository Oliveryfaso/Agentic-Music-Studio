import { FormEvent, useState } from "react";

import type { ReplanAIRunInput } from "../../shared/openapi";

export function PlanAdjustmentForm({ busy, onSubmit }: { busy: boolean; onSubmit: (adjustment: ReplanAIRunInput["adjustment"]) => void }) {
  const [bpm, setBpm] = useState("");
  const [key, setKey] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetBpm = bpm.trim() === "" ? null : Number(bpm);
    if (targetBpm !== null && (!Number.isFinite(targetBpm) || targetBpm < 40 || targetBpm > 220)) setError("BPM 需在 40–220 之间。");
    else if (!note.trim()) setError("请说明希望 Agent 调整什么。");
    else {
      setError(null);
      onSubmit({ schema_version: "plan-adjustment.v1", target_bpm: targetBpm, target_key: key.trim() || null, sections: null, instrumentation: null, note: note.trim() });
    }
  }

  return (
    <form className="adjustment-form" onSubmit={submit}>
      <header><p className="eyebrow">REPLAN / IMMUTABLE CHILD RUN</p><h2>调整 Plan</h2></header>
      <div className="adjustment-grid">
        <label><span>调整后的 BPM</span><input type="number" min="40" max="220" value={bpm} onChange={(event) => setBpm(event.target.value)} /></label>
        <label><span>调整后的调性</span><input value={key} onChange={(event) => setKey(event.target.value)} /></label>
        <label><span>调整说明</span><textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} /></label>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
      <button className="secondary-inline" type="submit" disabled={busy}>创建调整后的 Plan</button>
    </form>
  );
}
