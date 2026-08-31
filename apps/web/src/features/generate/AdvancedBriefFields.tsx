import type { RefObject } from "react";

export interface AdvancedBriefValues {
  meter: "4/4" | "3/4";
  bpm: string;
  key: string;
  instruments: string;
  hardConstraints: string;
  softPreferences: string;
  negativeConstraints: string;
}

export function AdvancedBriefFields({
  values,
  onChange,
  detailsRef,
  bpmRef,
}: {
  values: AdvancedBriefValues;
  onChange: (field: keyof AdvancedBriefValues, value: string) => void;
  detailsRef: RefObject<HTMLDetailsElement | null>;
  bpmRef: RefObject<HTMLInputElement | null>;
}) {
  return <details className="advanced-brief" ref={detailsRef}>
    <summary><span>高级编曲约束</span><small>拍号、速度、调性、乐器与约束</small></summary>
    <div className="advanced-brief-grid">
      <Field label="拍号"><select value={values.meter} onChange={(event) => onChange("meter", event.target.value)}><option>4/4</option><option>3/4</option></select></Field>
      <Field label="目标 BPM"><input ref={bpmRef} type="number" min="40" max="220" value={values.bpm} onChange={(event) => onChange("bpm", event.target.value)} /></Field>
      <Field label="目标调性"><input value={values.key} onChange={(event) => onChange("key", event.target.value)} placeholder="D dorian" /></Field>
      <Field label="偏好乐器"><input value={values.instruments} onChange={(event) => onChange("instruments", event.target.value)} placeholder="warm pad, soft pulse" /></Field>
      <Field label="硬约束"><input value={values.hardConstraints} onChange={(event) => onChange("hardConstraints", event.target.value)} /></Field>
      <Field label="偏好"><input value={values.softPreferences} onChange={(event) => onChange("softPreferences", event.target.value)} /></Field>
      <Field label="禁止项"><input value={values.negativeConstraints} onChange={(event) => onChange("negativeConstraints", event.target.value)} /></Field>
    </div>
  </details>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label><span>{label}</span>{children}</label>;
}
