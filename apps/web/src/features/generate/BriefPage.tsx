import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../../shared/api";
import type { CreateAIRunInput } from "../../shared/openapi";
import { readProject } from "../projects/projectApi";
import { navigate } from "../../app/routes";
import { StatusBanner } from "../../app/StatusBanner";
import { createRun } from "./generateApi";
import { BriefForm } from "./BriefForm";
import { readModelSettings } from "../settings/modelSettingsApi";

export function BriefPage({ projectId }: { projectId: string }) {
  const [accepted, setAccepted] = useState(false);
  const submission = useMemo<{ active: boolean; request: { body: string; key: string } | null }>(()=>({active:false,request:null}),[projectId]);
  useEffect(()=>{submission.active=true;return()=>{submission.active=false;};},[submission]);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => readProject(projectId) });
  const model = useQuery({ queryKey: ["model-settings"], queryFn: readModelSettings, retry: false, staleTime: 0 });
  const configuration = !model.isError && !model.isFetching ? model.data?.state : undefined;
  const canPlan = configuration === "configured" || configuration === "not_configured";
  const freeFallback = configuration === "not_configured";
  const creation = useMutation({
    mutationFn: async (brief: NonNullable<CreateAIRunInput["brief"]>) => {
      if (!project.data?.active_branch_id || !project.data.head_revision_id) throw new Error("Project 没有可用的基线 Revision");
      const input: CreateAIRunInput = {
        branch_id: project.data.active_branch_id,
        base_revision_id: project.data.head_revision_id,
        run_type: "generate",
        brief,
        max_model_requests: 1,
        max_total_tokens: 12000,
      };
      const body=JSON.stringify(input);
      if(submission.request && submission.request.body!==body) throw new Error("上次提交尚未确认，请先返回作品核对任务。");
      const pending=submission.request??{body,key:`web-generate-${crypto.randomUUID()}`};
      submission.request=pending;
      try { return await createRun(projectId,input,pending.key); }
      catch(error) {
        // Validation rejection cannot have queued a Run; an unknown result keeps its identity.
        if(error instanceof ApiError && error.status===422 && submission.request===pending) submission.request=null;
        throw error;
      }
    },
    onSuccess: (run) => {
      if(!submission.active || run.project_id!==projectId)return;
      submission.request=null;
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
      {creation.isError && <><StatusBanner tone="danger" message="Brief 提交失败" detail={creation.error instanceof ApiError ? message(creation.error) : "上次提交结果尚未确认。重试需保持原想法，或返回作品核对任务。"} /><a className="secondary-inline" href="/">返回作品核对任务</a></>}
      {configuration !== "configured" && <section aria-label="模型配置">
        <StatusBanner tone={model.isError ? "danger" : "warning"} message={model.isError ? "无法读取模型配置" : model.isFetching ? "正在读取模型配置…" : freeFallback ? "未启用模型 · 可使用免费模板" : "无法确认模型配置"} detail={freeFallback ? "使用本地确定性模板，不理解任意描述；计划需确认后继续。" : "请刷新配置后再提交。填写的想法会保留，不会自动测试连接。"} />
        <div className="action-row"><a className="secondary-inline" href="/settings">配置 API Key</a><button type="button" disabled={model.isFetching} onClick={()=>void model.refetch()}>刷新模型配置</button></div>
      </section>}
      <p className="form-note">{freeFallback ? "当前服务未配置 Key，将使用确定性模板，不发送模型请求。" : configuration === "configured" ? "提交后，描述将发送至 DeepSeek，可能计费；先确认计划，再试听。" : "配置尚未确认，暂不提交生成请求。"}</p>
      <div className="brief-layout"><BriefForm disabled={!canPlan || creation.isPending} isSubmitting={creation.isPending} submitLabel={freeFallback ? "使用免费模板规划" : "提交 Brief 并规划"} onSubmit={(brief) => { if (canPlan && !creation.isPending) creation.mutate(brief); }} /><details className="creation-guide"><summary>创作帮助</summary><p>描述想法 → 确认计划 → A/B 试听 → Studio → 导出。任务保留进度，可从作品列表恢复。</p></details></div>
    </section>
  );
}

function message(error: Error): string {
  return error instanceof ApiError ? error.message : error.message || "客户端发生未知错误";
}
