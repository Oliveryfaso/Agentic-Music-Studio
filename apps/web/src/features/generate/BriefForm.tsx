import { FormEvent, useState } from "react";

import type { CreateAIRunInput } from "../../shared/openapi";

type Brief = CreateAIRunInput["brief"];

export function BriefForm({ disabled, onSubmit }: { disabled: boolean; onSubmit: (brief: Brief) => void }) {
  const [title, setTitle] = useState("");
  const [purpose, setPurpose] = useState("");
  const [duration, setDuration] = useState("90");
  const [meter, setMeter] = useState<"4/4" | "3/4">("4/4");
  const [bpm, setBpm] = useState("");
  const [key, setKey] = useState("");
  const [moods, setMoods] = useState("");
  const [instruments, setInstruments] = useState("");
  const [hardConstraints, setHardConstraints] = useState("");
  const [softPreferences, setSoftPreferences] = useState("");
  const [negativeConstraints, setNegativeConstraints] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const forbidden = /人声|演唱|歌唱|vocal|sing(?:er|ing)?/i;
    if (forbidden.test(`${purpose} ${hardConstraints}`)) {
      setError("首版只支持纯器乐，请移除人声或演唱要求。");
      return;
    }
    const durationSeconds = Number(duration);
    const targetBpm = bpm.trim() === "" ? null : Number(bpm);
    const moodList = splitList(moods);
    if (!title.trim() || !purpose.trim()) setError("请填写作品标题和用途。");
    else if (!Number.isFinite(durationSeconds) || durationSeconds < 60 || durationSeconds > 300) setError("时长需在 60–300 秒之间。");
    else if (targetBpm !== null && (!Number.isFinite(targetBpm) || targetBpm < 40 || targetBpm > 220)) setError("BPM 需在 40–220 之间。");
    else if (moodList.length < 1 || moodList.length > 6) setError("请填写 1–6 个情绪关键词。");
    else {
      setError(null);
      onSubmit({
        schema_version: "composition-brief.v1",
        title: title.trim(),
        purpose: purpose.trim(),
        style: "synth_ambient",
        duration_seconds: durationSeconds,
        meter,
        target_bpm: targetBpm,
        target_key: key.trim() || null,
        moods: moodList,
        preferred_instruments: splitList(instruments),
        hard_constraints: splitList(hardConstraints),
        soft_preferences: splitList(softPreferences),
        negative_constraints: splitList(negativeConstraints),
      });
    }
  }

  return (
    <form className="brief-form" onSubmit={submit}>
      <div className="brief-grid">
        <Field label="作品标题"><input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={120} /></Field>
        <Field label="用途"><textarea value={purpose} onChange={(event) => setPurpose(event.target.value)} rows={3} /></Field>
        <Field label="情绪"><input value={moods} onChange={(event) => setMoods(event.target.value)} placeholder="weightless, curious" /></Field>
        <Field label="偏好乐器"><input value={instruments} onChange={(event) => setInstruments(event.target.value)} placeholder="warm pad, soft pulse" /></Field>
        <Field label="目标时长（秒）"><input type="number" min="60" max="300" value={duration} onChange={(event) => setDuration(event.target.value)} /></Field>
        <Field label="拍号"><select value={meter} onChange={(event) => setMeter(event.target.value as "4/4" | "3/4")}><option>4/4</option><option>3/4</option></select></Field>
        <Field label="目标 BPM"><input type="number" min="40" max="220" value={bpm} onChange={(event) => setBpm(event.target.value)} /></Field>
        <Field label="目标调性"><input value={key} onChange={(event) => setKey(event.target.value)} placeholder="D dorian" /></Field>
        <Field label="硬约束"><input value={hardConstraints} onChange={(event) => setHardConstraints(event.target.value)} /></Field>
        <Field label="偏好"><input value={softPreferences} onChange={(event) => setSoftPreferences(event.target.value)} /></Field>
        <Field label="禁止项"><input value={negativeConstraints} onChange={(event) => setNegativeConstraints(event.target.value)} /></Field>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
      <div className="action-row">
        <button className="primary-button" type="submit" disabled={disabled}>{disabled ? "提交中…" : "提交 Brief 并规划"}</button>
        <span className="form-note">Agent 只生成 Plan；你批准后才会写入 Revision。</span>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label><span>{label}</span>{children}</label>;
}

function splitList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}
