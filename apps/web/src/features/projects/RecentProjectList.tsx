import type { ProjectSummary } from "../../shared/openapi";
import { ProjectCard } from "./ProjectCard";

const RECENT_LIMIT = 6;

export function RecentProjectList({
  projects,
  expanded,
  onExpandedChange,
  filtered,
}: {
  projects: ProjectSummary[];
  expanded: boolean;
  onExpandedChange: (value: boolean) => void;
  filtered: boolean;
}) {
  const ordered = [...projects].sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
  if (ordered.length === 0) return <section className="empty-state filtered-empty"><h2>没有符合筛选条件的作品</h2><p>清除搜索词或切换状态即可恢复完整列表。</p></section>;
  const visible = expanded || filtered ? ordered : ordered.slice(0, RECENT_LIMIT);
  return <>
    <div className="project-grid" aria-label="作品列表">
      {visible.map((project) => <ProjectCard key={project.project_id} project={project} />)}
    </div>
    {!filtered && ordered.length > RECENT_LIMIT && <button className="secondary-inline project-history-toggle" type="button" onClick={() => onExpandedChange(!expanded)}>
      {expanded ? "收起测试历史" : "全部项目与测试历史"}
    </button>}
  </>;
}
