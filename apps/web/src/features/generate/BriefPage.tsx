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
      <a className="back-link" href="/">← 返回作品</a>
      <header className="workflow-hero">
        <div><p className="eyebrow">NEW COMPOSITION · {project.data.name}</p><h1 id="brief-title">定义这首作品</h1><p>你给出方向，Agent 提出编曲计划。先一起确认，再把它变成音乐。</p></div>
        <span className={`storage-state ${project.data.storage_root_status}`}>{project.data.storage_root_status === "ready" ? "存储已就绪" : `存储需检查 · ${project.data.storage_root_status}`}</span>
      </header>
      {accepted && <StatusBanner message="Run 已进入持久队列" detail="正在转到可恢复的 Plan 与进度页面。" />}
      {creation.isError && <StatusBanner tone="danger" message="Brief 提交失败" detail={message(creation.error)} />}
      <div className="brief-layout"><BriefForm disabled={creation.isPending} onSubmit={(brief) => creation.mutate(brief)} /><aside className="creation-guide"><p className="eyebrow">THE CREATIVE PROCESS</p><h2>接下来会发生什么？</h2><ol><li><span>1</span><div><strong>先定方向</strong><p>写下想法，Agent 提出段落、节奏与配器计划。你可以调整或拒绝。</p></div></li><li><span>2</span><div><strong>听见两种可能</strong><p>批准计划后生成 A/B 试听。比较差异，选择喜欢的方向。</p></div></li><li><span>3</span><div><strong>继续打磨，带走作品</strong><p>在 Studio 编辑音轨与音符，也可以让 AI 修改局部，最后导出音频和工程。</p></div></li></ol><p className="guide-note">不用一直守着页面。任务进度会保留，可以从作品列表继续。</p></aside></div>
    </section>
  );
}

function message(error: Error): string {
  return error instanceof ApiError ? error.message : error.message || "客户端发生未知错误";
}
