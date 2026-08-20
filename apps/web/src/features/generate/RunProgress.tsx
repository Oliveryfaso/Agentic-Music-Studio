import type { AIRun } from "../../shared/openapi";
import type { RunUiState } from "./runState";

const PHASE_LABELS: Record<RunUiState["phase"], string> = {
  draft: "准备 Brief", submitting: "提交中", queued: "已排队", planning: "Agent 正在规划", waiting_approval: "等待审批",
  approving: "正在批准", rejecting: "正在拒绝", adjusting: "正在调整", child_queued: "子 Run 已排队", child_planning: "子 Run 正在规划",
  child_waiting_approval: "子 Run 等待审批", materializing: "正在写入 Revision", waiting_worker: "正在渲染导出", succeeded: "作品已生成并写入 Revision",
  rejected: "计划已拒绝", cancelled: "Run 已取消", failed: "Run 执行失败", partial_success: "已有安全 Revision，导出未完整完成",
};

export function RunProgress({ run, state }: { run: AIRun; state: RunUiState }) {
  const completed = run.progress.completed_export_steps.length;
  return (
    <aside className={`run-progress phase-${state.phase}`} aria-live="polite">
      <div><p className="eyebrow">AUTHORITATIVE RUN</p><h1>{PHASE_LABELS[state.phase]}</h1><p>Run {run.run_id}</p></div>
      <div className="progress-facts">
        <span>连接 <strong>{connectionLabel(state.connection)}</strong></span>
        <span>事件序号 <strong>{state.lastSequence}</strong></span>
        <span>导出 <strong>{completed}/{run.progress.total_export_steps}</strong></span>
      </div>
      {completed > 0 && <p className="completed-steps">已完成：{run.progress.completed_export_steps.join(" · ")}</p>}
      {state.errorCode && <p className="safe-error">错误代码：{state.errorCode}</p>}
    </aside>
  );
}

function connectionLabel(value: RunUiState["connection"]): string {
  return ({ initial_read: "读取事实", connecting: "连接中", live: "实时", reconnecting: "重连中", replaying: "回放中", terminal_closed: "已终止", offline_error: "离线" })[value];
}
