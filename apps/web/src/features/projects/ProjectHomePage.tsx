import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState, useRef } from "react";

import { navigate } from "../../app/routes";
import { ApiError } from "../../shared/api";
import {createPianoStudy} from "../studio/pianoApi";
import {ClassicalScoreEntry} from "./ClassicalScoreEntry";
import { createProject, listProjects } from "./projectApi";
import { ProjectFilters } from "./ProjectFilters";
import { RecentProjectList } from "./RecentProjectList";

export function ProjectHomePage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [expanded, setExpanded] = useState(false);
  const studyKey=useRef<string|null>(null);
  const study=useMutation({mutationFn:()=>{
    studyKey.current??='web-piano-study:'+crypto.randomUUID();
    return createPianoStudy(studyKey.current);
  },onSuccess:(value)=>{studyKey.current=null;void queryClient.invalidateQueries({queryKey:["projects"]});
    navigate({name:"studio",projectId:value.project_id,revisionId:value.revision_id});}});
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
      <header className="project-home-hero"><h1 id="project-home-title">作品</h1><span className="status-pill">古典与爵士</span></header>

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
          
        </section>
      )}
      {projects.data && projects.data.length > 0 && (
        <section className="project-catalog" aria-label="作品目录">
          <div className="catalog-heading"><div><h2>最近作品</h2></div><span>{projects.data.length} 个作品</span></div>
          <ProjectFilters search={search} status={status} onSearchChange={setSearch} onStatusChange={setStatus} />
          <RecentProjectList
            projects={projects.data.filter((project) => project.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) && (status === "all" || project.status === status))}
            expanded={expanded}
            onExpandedChange={setExpanded}
            filtered={search.trim() !== "" || status !== "all"}
          />
        </section>
      )}
      <section className="new-work-start" aria-label="新建作品">      <form className="create-project-form" onSubmit={submit}>
        <div>
          
          <label htmlFor="project-name">新建作品</label>
          
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
        {creation.isSuccess && <div className="project-created" role="status"><span>作品已创建</span><button className="secondary-inline" type="button" onClick={() => navigate({ name: "brief", projectId: creation.data.project_id })}>开始创作 →</button></div>}
      </form>

      <section className="piano-study-entry" aria-label="钢琴练习谱入口">
        <div><strong>从一段钢琴琶音开始</strong><span>自制练习谱 · 30 秒</span></div>
        <button type="button" className="secondary-inline" disabled={study.isPending} onClick={()=>study.mutate()}>{study.isPending?"正在创建练习谱…":study.isError?"重试新建练习谱":"新建钢琴练习谱"}</button>
        {study.error&&<p className="field-error" role="alert">{errorMessage(study.error)}</p>}
      </section>
      <ClassicalScoreEntry/>
</section>
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
