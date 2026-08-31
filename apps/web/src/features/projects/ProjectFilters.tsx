export function ProjectFilters({
  search,
  status,
  onSearchChange,
  onStatusChange,
}: {
  search: string;
  status: string;
  onSearchChange: (value: string) => void;
  onStatusChange: (value: string) => void;
}) {
  return <div className="project-filters" aria-label="筛选作品">
    <label><span>搜索作品</span><input type="search" value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder="按名称搜索" /></label>
    <label><span>作品状态</span><select value={status} onChange={(event) => onStatusChange(event.target.value)}><option value="all">全部状态</option><option value="active">进行中</option><option value="archived">已归档</option></select></label>
  </div>;
}
