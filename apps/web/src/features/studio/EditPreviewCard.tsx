import { audioContentUrl } from "../../shared/api";
import type { RunEditPreview } from "../../shared/openapi";

export function EditPreviewCard({ preview, busy, rootReady, onDecision }: {
  preview: RunEditPreview;
  busy: boolean;
  rootReady: boolean;
  onDecision: (action: "approve" | "reject" | "cancel") => void;
}) {
  const ready = rootReady
    && preview.preview_availability === "available"
    && preview.preview_artifact_id !== null;
  return <article className="edit-preview-card" aria-labelledby="edit-preview-title">
    <div className="panel-heading"><div><p className="eyebrow">RENDERED EVIDENCE</p>
      <h3 id="edit-preview-title">Edit Preview</h3></div>
      <span className={`status-pill ${preview.preview_availability}`}>
        {ready ? "可审批" : preview.preview_availability}
      </span>
    </div>
    {ready && preview.preview_artifact_id
      ? <audio controls preload="metadata" src={audioContentUrl(preview.preview_artifact_id)} />
      : <p>试听工件尚不可用；审批保持锁定。</p>}
    <dl>
      <div><dt>实际影响</dt><dd>L{preview.actual_change_impact}</dd></div>
      <div><dt>范围差异</dt><dd>{preview.structural_diff.length || "无"}</dd></div>
    </dl>
    <ul>{preview.structural_diff.map((entry, index) =>
      <li key={`${String(entry.path ?? "diff")}-${index}`}>{String(entry.summary ?? entry.path ?? "选区变化")}</li>)}</ul>
    <div className="edit-preview-actions">
      <button className="primary-button" type="button" disabled={!ready || busy}
        onClick={() => onDecision("approve")}>批准 Preview</button>
      <button type="button" disabled={busy} onClick={() => onDecision("reject")}>拒绝</button>
      <button type="button" disabled={busy} onClick={() => onDecision("cancel")}>取消 Run</button>
    </div>
  </article>;
}
