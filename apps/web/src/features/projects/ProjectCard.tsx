import { navigate } from "../../app/routes";
import type { AIRunStatus, ProjectSummary } from "../../shared/openapi";

const RECOVERABLE: ReadonlySet<AIRunStatus> = new Set([
  "queued",
  "planning",
  "waiting_approval",
  "materializing",
  "waiting_worker",
]);

const STATUS_LABELS = {
  queued: "等待执行",
  planning: "正在规划",
  waiting_approval: "等待审批",
  materializing: "正在创建版本",
  waiting_worker: "正在导出",
  succeeded: "已完成",
  rejected: "已拒绝",
  failed: "失败",
  cancelled: "已取消",
} as const;

export function ProjectCard({ project }: { project: ProjectSummary }) {
  const run = project.latest_run;
  const runLabel = run ? STATUS_LABELS[run.status] : "尚未生成";
  const recoverable = run !== null && RECOVERABLE.has(run.status);
  return (
    <article className="project-card">
      <div className="project-card-heading">
        <div>
          <p className="eyebrow">PROJECT</p>
          <h2>{project.name}</h2>
        </div>
        <span className={`project-run-status ${run?.status ?? "idle"}`}>
          <i aria-hidden="true" />{runLabel}
        </span>
      </div>
      <p className="project-updated">更新于 {formatDate(project.updated_at)}</p>
      <div className="project-card-actions">
        {project.has_playable_revision && (
          <button
            className="primary-button"
            type="button"
            aria-label={`打开 ${project.name} 最新版本`}
            onClick={() => navigate({
              name: "studio",
              projectId: project.project_id,
              revisionId: project.head_revision_id,
            })}
          >
            打开最新版本
          </button>
        )}
        {recoverable && run && (
          <button
            className="agent-button"
            type="button"
            aria-label={`恢复${runLabel}`}
            onClick={() => navigate({ name: "run", runId: run.run_id })}
          >
            恢复 Agent Run
          </button>
        )}
        <button
          className="secondary-inline"
          type="button"
          onClick={() => navigate({ name: "brief", projectId: project.project_id })}
        >
          新建编曲
        </button>
        <button
          className="text-button project-import-button"
          type="button"
          onClick={() => navigate({ name: "import", projectId: project.project_id })}
        >
          导入音频
        </button>
      </div>
    </article>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
