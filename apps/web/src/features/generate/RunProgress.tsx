import type { AIRun } from "../../shared/openapi";
import type { RunUiState } from "./runState";

const PHASE_LABELS: Record<RunUiState["phase"], string> = {
  draft: "准备 Brief", submitting: "提交中", queued: "已排队", planning: "Agent 正在规划", waiting_approval: "等待审批",
  approving: "正在批准", rejecting: "正在拒绝", adjusting: "正在调整", child_queued: "子 Run 已排队", child_planning: "子 Run 正在规划",
  child_waiting_approval: "新计划等待确认", materializing: "正在保存选定的作品", waiting_worker: "正在渲染导出", succeeded: "作品已生成，正式版本已保存",
  generating_candidates: "正在生成候选 A / B", rendering_candidate_previews: "正在渲染候选试听", criticizing: "Critic 正在比较证据",
  repairing_candidate: "正在执行一次局部修复", waiting_candidate_selection: "等待选择候选",
  rejected: "计划已拒绝", cancelled: "创作任务已取消", failed: "这次创作未能完成", partial_success: "作品已保存，部分导出尚未完成",
};

export function RunProgress({ run, state }: { run: AIRun; state: RunUiState }) {
  const completed = run.progress.completed_export_steps.length;
  return (
    <aside className={`run-progress phase-${state.phase}`} aria-live="polite">
      <div><p className="eyebrow">CREATION IN PROGRESS</p><h1>{PHASE_LABELS[state.phase]}</h1><p className="run-lede">{run.pending_action === "approve_plan" ? "阅读下方编曲计划。合适就批准，也可以提出调整。" : run.pending_action === "select_candidate" ? "两份候选已经准备好。试听并选择你更喜欢的方向。" : run.status === "succeeded" ? "可以进入 Studio 继续打磨，或前往导出页下载作品。" : run.status === "failed" ? "已完成的结果会保留。查看错误详情后，可以重试一次新任务。" : run.status === "cancelled" || run.status === "rejected" ? "这次任务已结束。可以返回作品，重新定义音乐方向。" : "正在按计划推进。进度会自动更新，离开后也可以回来继续。"}</p></div>
      <div className="progress-facts">
        <span>进度同步 <strong>{connectionLabel(state.connection)}</strong></span>
        <span>导出 <strong>{completed}/{run.progress.total_export_steps}</strong></span>
      </div>
      <details className="run-technical"><summary>运行标识与同步详情</summary><p>Run {run.run_id} · 事件序号 {state.lastSequence}</p>{completed > 0 && <p>已完成：{run.progress.completed_export_steps.join(" · ")}</p>}</details>
      {state.errorCode && <p className="safe-error">错误代码：{state.errorCode}</p>}
    </aside>
  );
}

function connectionLabel(value: RunUiState["connection"]): string {
  return ({ initial_read: "读取中", connecting: "连接中", live: "实时", reconnecting: "重连中", replaying: "补齐记录中", terminal_closed: "任务已结束", offline_error: "已断开" })[value];
}
