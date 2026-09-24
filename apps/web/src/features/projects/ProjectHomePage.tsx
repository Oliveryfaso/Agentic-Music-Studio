import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { navigate } from "../../app/routes";
import { MotifScore } from "../../app/MotifScore";
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
          <p className="eyebrow">YOUR IDEAS. YOUR MUSIC.</p>
          <h1 id="project-home-title">把脑海里的声音，<br /><span>变成你的作品。</span></h1>
          <p>说出音乐的用途与情绪，让 Agent 帮你规划、编曲。试听两个方向，在 Studio 里继续打磨——每一步，都由你决定。</p>
          <div className="home-capabilities"><span>4 种音乐风格</span><span>可编辑多轨</span><span>可追溯的 Agent 协作</span></div>
        </div>
        <MotifScore />
      </div>

      <form className="create-project-form" onSubmit={submit}>
        <div>
          <p className="eyebrow">START SOMETHING NEW</p>
          <label htmlFor="project-name">给下一个灵感起个名字</label>
          <p>创建后，可以描述音乐想法，也可以导入已有音频。</p>
        </div>
        <div className="create-project-controls">
          <input
            id="project-name"
            aria-label="作品名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            placeholder="例如：雨后的漫步"
            required
          />
          <button className="primary-button" type="submit" disabled={creation.isPending}>
            {creation.isPending ? "创建中…" : "创建作品"}
          </button>
        </div>
        {creation.isError && <p className="field-error" role="alert">{errorMessage(creation.error)}</p>}
        {creation.isSuccess && <div className="project-created" role="status"><span>作品已创建。接下来，告诉 Agent 你想做什么样的音乐。</span><button className="secondary-inline" type="button" onClick={() => navigate({ name: "brief", projectId: creation.data.project_id })}>开始创作 →</button></div>}
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
          <p>从上方创建第一首作品。你的编曲、试听结果和修改版本都会保存在这里，下次可以接着做。</p>
        </section>
      )}
      {projects.data && projects.data.length > 0 && (
        <section className="project-catalog" aria-label="作品目录">
          <div className="catalog-heading"><div><p className="eyebrow">YOUR COLLECTION</p><h2>继续你的创作</h2></div><span>{projects.data.length} 个作品</span></div>
          <ProjectFilters search={search} status={status} onSearchChange={setSearch} onStatusChange={setStatus} />
          <RecentProjectList
            projects={projects.data.filter((project) => project.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) && (status === "all" || project.status === status))}
            expanded={expanded}
            onExpandedChange={setExpanded}
            filtered={search.trim() !== "" || status !== "all"}
          />
        </section>
      )}
      <aside className="portfolio-entry">
        <div><strong>好作品背后，也有清晰的过程。</strong><p>了解 Agent 如何规划、等待你的确认，并留下可检查的执行记录。</p></div>
        <button className="secondary-inline" type="button" onClick={() => navigate({ name: "about" })}>认识 Motif Forge ↗</button>
      </aside>
    </section>
  );
}

function ProjectLoading() {
  return (
    <section className="loading-state" role="status" aria-label="正在载入项目">
      <div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div>
      <h2>正在打开你的作品集</h2>
      <p>正在读取最近的作品和创作进度。</p>
    </section>
  );
}

function errorMessage(error: Error): string {
  return error instanceof ApiError ? error.message : "暂时连接不到本地服务。请确认 Motif Forge 已启动，然后重试。";
}
