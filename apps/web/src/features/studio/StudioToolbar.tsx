import type { EditorState } from "./editorState";
import { canSaveDraft } from "./editorState";

export function StudioToolbar({ state, onUndo, onRedo, onSave, onUndoRevision }: {
  state: EditorState;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onUndoRevision: () => void;
}) {
  return <div className="studio-toolbar" aria-label="编辑工具栏">
    <button type="button" onClick={onUndo} disabled={state.historyCursor === 0}>撤销草稿</button>
    <button type="button" onClick={onRedo} disabled={state.historyCursor === state.commands.length}>重做草稿</button>
    <span role="status">{state.historyCursor} 个未保存修改</span>
    <button type="button" className="primary-inline" onClick={onSave} disabled={!canSaveDraft(state)}>{state.saveState === "saving" ? "保存中…" : "保存 Revision"}</button>
    <button type="button" onClick={onUndoRevision} disabled={state.historyCursor > 0}>撤销已保存 Revision</button>
    {state.saveState === "error" && <span className="field-error" role="alert">保存失败，草稿仍保留</span>}
    {state.conflict && <span className="field-error" role="alert">分支已更新到 {state.conflict.serverRevisionId}，请先处理冲突</span>}
  </div>;
}
