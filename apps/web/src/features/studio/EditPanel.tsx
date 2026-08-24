import { useState } from "react";

import { ApiError } from "../../shared/api";
import type { AIRun } from "../../shared/openapi";
import type { EditorSelection } from "./editorState";
import { createEditRun } from "./editRunApi";

export function EditPanel({
  projectId,
  branchId,
  baseRevisionId,
  selection,
  lockedRanges,
  rootReady,
  onRunCreated,
}: {
  projectId: string;
  branchId: string;
  baseRevisionId: string;
  selection: EditorSelection | null;
  lockedRanges: Array<{ track_id: string; start_tick: number; end_tick: number }>;
  rootReady: boolean;
  onRunCreated: (run: AIRun) => void;
}) {
  const [intent, setIntent] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = selection !== null && selection.trackIds.length > 0 && intent.trim() !== "";
  const submit = async () => {
    if (!valid || selection === null) return;
    setPending(true);
    setError(null);
    try {
      const run = await createEditRun(projectId, {
        branch_id: branchId,
        base_revision_id: baseRevisionId,
        run_type: "edit",
        brief: null,
        edit_request: {
          intent: intent.trim(),
          selection: {
            track_ids: selection.trackIds,
            start_tick: selection.startTick,
            end_tick: selection.endTick,
          },
          locked_ranges: lockedRanges,
          allow_local_catalog: true,
          seed: 0,
        },
        max_model_requests: 1,
        max_total_tokens: 4000,
      }, `web-edit-run-${crypto.randomUUID()}`);
      onRunCreated(run);
    } catch (caught) {
      setError(caught instanceof ApiError ? `${caught.message}（${caught.code}）` : "无法创建 Edit Run");
    } finally {
      setPending(false);
    }
  };
  return <section className="edit-panel" aria-labelledby="edit-panel-title">
    <div>
      <p className="eyebrow">PARENT GRAPH / BOUNDED EDIT</p>
      <h2 id="edit-panel-title">AI 选区编辑</h2>
      <p>{selection
        ? `${selection.trackIds.length} 条轨道 · Tick ${selection.startTick}–${selection.endTick}`
        : "先在时间线选择一个 Clip 或范围。"}</p>
    </div>
    <label>AI 编辑要求
      <textarea value={intent} onChange={(event) => setIntent(event.target.value)}
        placeholder="例如：把这里的 Pad 降低 2 dB" rows={3} />
    </label>
    <div className="edit-panel-actions">
      <button className="primary-button" type="button" disabled={!valid || pending}
        onClick={() => void submit()}>{pending ? "提交中…" : "运行选区编辑"}</button>
      <span>{rootReady ? "L0/L1 自动提交；L2/L3 先渲染 Preview" : "外置 Root 离线：仅安全参数编辑可继续"}</span>
    </div>
    {error && <p className="field-error" role="alert">{error}</p>}
  </section>;
}
