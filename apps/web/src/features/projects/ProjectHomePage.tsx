import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { navigate } from "../../app/routes";
import { ApiError } from "../../shared/api";
import { createProject, listProjects } from "./projectApi";
import { ProjectFilters } from "./ProjectFilters";
import { RecentProjectList } from "./RecentProjectList";

export function ProjectHomePage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [expanded, setExpanded] = useState(false);
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => listProjects() });
  const creation = useMutation({
    mutationFn: (projectName: string) => createProject(
      { name: projectName },
      `web-project-${crypto.randomUUID()}`,
    ),
    onSuccess: async () => {
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = name.trim();
    if (value === "" || creation.isPending) return;
    creation.mutate(value);
  }

  return (
    <section className="project-home" aria-labelledby="project-home-title">
      <div className="project-home-hero">
        <div>
          <p className="eyebrow">PROJECT HOME / AGENT JOURNEYS</p>
          <h1 id="project-home-title">从一个 Brief，锻造一首完整作品。</h1>
          <p>创建作品，审阅 Agent 的结构计划，并从持久 Run 或最新 Revision 继续。</p>
        </div>
        <div className="agent-orbit" aria-hidden="true"><i /><i /><i /></div>
      </div>

      <aside className="portfolio-entry">
        <div><p className="eyebrow">S7 PORTFOLIO RELEASE</p><strong>查看 Agent 架构、恢复语义与 96-case Eval。</strong></div>
        <button className="secondary-inline" type="button" onClick={() => navigate({ name: "about" })}>了解工程闭环</button>
      </aside>

      <form className="create-project-form" onSubmit={submit}>
        <div>
          <label htmlFor="project-name">作品名称</label>
          <p>只创建 Project 与初始 Revision；音乐生成仍需单独提交和审批。</p>
        </div>
        <div className="create-project-controls">
          <input
            id="project-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            placeholder="例如：Orbital Glass"
            required
          />
          <button className="primary-button" type="submit" disabled={creation.isPending}>
            {creation.isPending ? "创建中…" : "创建作品"}
          </button>
        </div>
        {creation.isError && <p className="field-error" role="alert">{errorMessage(creation.error)}</p>}
      </form>

      {projects.isPending && <ProjectLoading />}
      {projects.isError && (
        <section className="error-state" role="alert">
          <span>!</span>
          <div>
            <h2>无法载入作品</h2>
            <p>{errorMessage(projects.error)}</p>
            <button type="button" onClick={() => void projects.refetch()}>重试载入</button>
          </div>
        </section>
      )}
      {projects.data?.length === 0 && (
        <section className="empty-state">
          <div className="empty-wave" aria-hidden="true">⌁</div>
          <h2>还没有作品</h2>
          <p>先命名第一个 Project。创建后可以从空白 Brief 生成，也可以导入已有音频。</p>
        </section>
      )}
      {projects.data && projects.data.length > 0 && (
        <section className="project-catalog" aria-label="Project catalog">
          <ProjectFilters search={search} status={status} onSearchChange={setSearch} onStatusChange={setStatus} />
          <RecentProjectList
            projects={projects.data.filter((project) => project.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) && (status === "all" || project.status === status))}
            expanded={expanded}
            onExpandedChange={setExpanded}
            filtered={search.trim() !== "" || status !== "all"}
          />
        </section>
      )}
    </section>
  );
}

function ProjectLoading() {
  return (
    <section className="loading-state" role="status" aria-label="正在载入项目">
      <div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div>
      <h2>读取 Project Ledger</h2>
      <p>正在从 PostgreSQL 读取作品、Revision 与可恢复 Run。</p>
    </section>
  );
}

function errorMessage(error: Error): string {
  return error instanceof ApiError ? error.message : "发生了未分类的客户端错误";
}
