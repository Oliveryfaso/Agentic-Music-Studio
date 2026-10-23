import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../../shared/api";
import type { CreateAIRunInput } from "../../shared/openapi";
import { readProject } from "../projects/projectApi";
import { navigate } from "../../app/routes";
import { StatusBanner } from "../../app/StatusBanner";
import { createRun } from "./generateApi";
import { BriefForm } from "./BriefForm";

export function BriefPage({ projectId }: { projectId: string }) {
  const [accepted, setAccepted] = useState(false);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => readProject(projectId) });
  const creation = useMutation({
    mutationFn: (brief: NonNullable<CreateAIRunInput["brief"]>) => {
      if (!project.data?.active_branch_id || !project.data.head_revision_id) throw new Error("Project 没有可用的基线 Revision");
      return createRun(projectId, {
        branch_id: project.data.active_branch_id,
        base_revision_id: project.data.head_revision_id,
        run_type: "generate",
        brief,
        max_model_requests: 1,
        max_total_tokens: 12000,
      }, `web-generate-${crypto.randomUUID()}`);
    },
    onSuccess: (run) => {
      setAccepted(true);
      navigate({ name: "run", runId: run.run_id });
    },
  });

  if (project.isPending) return <section className="loading-state" role="status"><h2>正在准备创作空间</h2><p>读取作品的最新版本，随后即可填写音乐想法。</p></section>;
  if (project.isError) return <section className="error-state" role="alert"><span>!</span><div><h2>无法读取 Project</h2><p>{message(project.error)}</p></div></section>;

  return (
    <section className="generate-page" aria-labelledby="brief-title">
      <a className="back-link" href={project.data.head_revision_id?`/projects/${encodeURIComponent(projectId)}/studio/${encodeURIComponent(project.data.head_revision_id)}`:"/"}>← 返回{project.data.head_revision_id?" Studio":"作品"}</a>
      <header className="workflow-hero">
        <div><p className="workspace-back">{project.data.name}</p><h1 id="brief-title">新建编曲</h1></div>
        <span className={`storage-state ${project.data.storage_root_status}`}>{project.data.storage_root_status === "ready" ? "存储已就绪" : `存储需检查 · ${project.data.storage_root_status}`}</span>
      </header>
      {accepted && <StatusBanner message="Run 已进入持久队列" detail="正在转到可恢复的 Plan 与进度页面。" />}
      {creation.isError && <StatusBanner tone="danger" message="Brief 提交失败" detail={message(creation.error)} />}
      <div className="brief-layout"><BriefForm disabled={creation.isPending} onSubmit={(brief) => creation.mutate(brief)} /><details className="creation-guide"><summary>创作帮助</summary><p>描述想法 → 确认计划 → A/B 试听 → Studio → 导出。任务保留进度，可从作品列表恢复。</p></details></div>
    </section>
  );
}

function message(error: Error): string {
  return error instanceof ApiError ? error.message : error.message || "客户端发生未知错误";
}
