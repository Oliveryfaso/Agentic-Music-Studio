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

  if (project.isPending) return <section className="loading-state"><h2>读取 Project 基线</h2><p>Brief 将绑定当前 Branch 与 Revision。</p></section>;
  if (project.isError) return <section className="error-state" role="alert"><span>!</span><div><h2>无法读取 Project</h2><p>{message(project.error)}</p></div></section>;

  return (
    <section className="generate-page" aria-labelledby="brief-title">
      <header className="workflow-hero">
        <div><p className="eyebrow">BRIEF / PLAN / APPROVAL</p><h1 id="brief-title">定义这首作品</h1><p>描述音乐意图。Agent 会先形成结构化 Plan，不会直接改写作品。</p></div>
        <span className={`storage-state ${project.data.storage_root_status}`}>存储 {project.data.storage_root_status}</span>
      </header>
      {accepted && <StatusBanner message="Run 已进入持久队列" detail="正在转到可恢复的 Plan 与进度页面。" />}
      {creation.isError && <StatusBanner tone="danger" message="Brief 提交失败" detail={message(creation.error)} />}
      <BriefForm disabled={creation.isPending} onSubmit={(brief) => creation.mutate(brief)} />
    </section>
  );
}

function message(error: Error): string {
  return error instanceof ApiError ? error.message : error.message || "客户端发生未知错误";
}
