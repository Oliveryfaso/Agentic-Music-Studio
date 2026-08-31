import { useEffect, useReducer, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { navigate } from "../../app/routes";
import { StatusBanner } from "../../app/StatusBanner";
import { ApiError } from "../../shared/api";
import type { AIRun, ReplanAIRunInput } from "../../shared/openapi";
import { readProject } from "../projects/projectApi";
import { ExecutionPathStrip } from "../inspection/ExecutionPathStrip";
import { readRunGraph } from "../inspection/inspectionApi";
import {
  cancelRun,
  replanRun,
  resumeRun,
  retryRun,
  RunActionConflict,
  selectCandidate,
} from "./generateApi";
import { CandidateCompare, type CandidateDecision } from "./CandidateCompare";
import type { PlanDecision } from "./PlanReview";
import { PlanReview } from "./PlanReview";
import { PlanAdjustmentForm } from "./PlanAdjustmentForm";
import { RunProgress } from "./RunProgress";
import { watchRunEvents } from "./runEvents";
import { initialRunState, reduceRunState } from "./runState";

export function RunPage({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [run, setRun] = useState<AIRun | null>(null);
  const [state, dispatch] = useReducer(reduceRunState, initialRunState);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [studioReady, setStudioReady] = useState(false);
  const graphQuery = useQuery({
    queryKey: ["run-graph", runId],
    queryFn: () => readRunGraph(runId),
    enabled: run !== null,
  });

  useEffect(() => {
    const controller = new AbortController();
    void watchRunEvents(runId, {
      onAuthoritativeRun: (value) => { setRun(value); dispatch({ type: "authoritative", run: value }); },
      onEvent: (event) => {
        dispatch({ type: "event", event });
        void queryClient.invalidateQueries({ queryKey: ["run-graph", runId] });
      },
      onConnectionChange: (connection) => dispatch({ type: "connection", connection }),
    }, controller.signal).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(message(cause));
    });
    return () => controller.abort();
  }, [queryClient, runId]);

  useEffect(() => {
    setStudioReady(false);
    if (!run?.revision_id || (run.status !== "succeeded" && run.status !== "failed")) return;
    let current = true;
    void readProject(run.project_id).then((project) => {
      if (current) setStudioReady(project.head_revision_id === run.revision_id || project.revisions.some((revision) => revision.revision_id === run.revision_id));
    }).catch((cause: unknown) => { if (current) setError(message(cause)); });
    return () => { current = false; };
  }, [run?.project_id, run?.revision_id, run?.status]);

  function acceptAuthoritative(value: AIRun) {
    setRun(value);
    dispatch({ type: "authoritative", run: value });
  }

  async function action(operation: () => Promise<AIRun>, onSuccess?: (value: AIRun) => void, acceptResult = true) {
    if (busy) return;
    setBusy(true); setError(null); setFeedback(null);
    try {
      const value = await operation();
      if (acceptResult) acceptAuthoritative(value);
      onSuccess?.(value);
    } catch (cause) {
      if (cause instanceof RunActionConflict) {
        acceptAuthoritative(cause.authoritativeRun);
        setFeedback("Run 状态已由服务端更新");
      } else setError(message(cause));
    } finally { setBusy(false); }
  }

  function decide(decision: PlanDecision) {
    if (!run?.pending_plan_hash) return;
    void action(() => resumeRun(run.run_id, {
      expected_version: run.version,
      expected_plan_hash: run.pending_plan_hash as string,
      actor_id: decision.actorId,
      approval_assertion: decision.assertion,
      decision: decision.decision,
      note: decision.note,
    }, actionKey("resume")));
  }

  function replan(adjustment: ReplanAIRunInput["adjustment"]) {
    if (!run?.pending_plan_hash) return;
    void action(() => replanRun(run.run_id, {
      expected_version: run.version,
      expected_plan_hash: run.pending_plan_hash as string,
      adjustment,
    }, actionKey("replan")), (child) => navigate({ name: "run", runId: child.run_id }), false);
  }

  function decideCandidate(decision: CandidateDecision) {
    if (!run || run.pending_action !== "select_candidate") return;
    void action(() => selectCandidate(run.run_id, {
      expected_version: run.version,
      preview_id: decision.previewId ?? null,
      expected_candidate_id: decision.candidateId ?? null,
      expected_candidate_content_hash: decision.candidateContentHash ?? null,
      actor_id: "local-user",
      selection_assertion: decision.assertion,
      decision: decision.decision,
      note: decision.note,
    }, actionKey("select-candidate")));
  }

  if (!run) {
    return error
      ? <section className="error-state" role="alert"><span>!</span><div><h2>无法恢复 Run</h2><p>{error}</p></div></section>
      : <section className="loading-state"><div className="spectral-loader" aria-hidden="true"><i /><i /><i /><i /><i /></div><h2>恢复 Agent Run</h2><p>先读取 PostgreSQL 权威状态，再从已保存序号接续事件。</p></section>;
  }

  const canRetry = run.status === "failed" || run.status === "cancelled";
  const canCancel = !["succeeded", "rejected", "failed", "cancelled"].includes(run.status) && run.status !== "waiting_approval";
  const terminal = ["succeeded", "rejected", "failed", "cancelled"].includes(run.status);
  const actions = <div className="run-actions">
    <a className="secondary-inline" href={`/runs/${encodeURIComponent(run.run_id)}/inspect`}>检查 Run</a>
    {run.revision_id && <a className="secondary-inline" href={`/projects/${encodeURIComponent(run.project_id)}/exports/${encodeURIComponent(run.revision_id)}`}>查看导出</a>}
    {canCancel && <button className="danger-button" type="button" disabled={busy} onClick={() => void action(() => cancelRun(run.run_id, run.version, actionKey("cancel")))}>取消 Run</button>}
    {canRetry && <button className="secondary-inline" type="button" disabled={busy} onClick={() => void action(() => retryRun(run.run_id, run.version, actionKey("retry")), (child) => navigate({ name: "run", runId: child.run_id }))}>重试为新 Run</button>}
    {run.revision_id && studioReady && <button className="primary-button" type="button" onClick={() => navigate({ name: "studio", projectId: run.project_id, revisionId: run.revision_id as string })}>打开只读 Studio</button>}
  </div>;
  return (
    <section className="generate-page run-page">
      <RunProgress run={run} state={state} />
      {graphQuery.data && <ExecutionPathStrip graph={graphQuery.data} inspectorHref={`/runs/${encodeURIComponent(run.run_id)}/inspect`} />}
      {graphQuery.isError && <StatusBanner tone="warning" message="执行路径暂时不可用" detail="审批、候选选择、取消与结果操作不受影响。" />}
      {feedback && <StatusBanner tone="warning" message={feedback} detail="页面已重新读取权威 Run；请按当前状态继续。" />}
      {error && <StatusBanner tone="danger" message="操作未完成" detail={error} />}
      {terminal && run.revision_id && <section className="run-result-panel"><p className="eyebrow">AUTHORITATIVE RESULT</p><h2>Revision 已就绪</h2><p>生成结果已物化，可以进入 Studio 或检查导出。</p>{actions}</section>}
      {run.plan && (terminal
        ? <details className="run-plan-details"><summary>查看生成计划</summary><PlanReview plan={run.plan} busy={busy} onDecision={decide} reviewable={false} /></details>
        : <PlanReview plan={run.plan} busy={busy} onDecision={decide} reviewable={run.pending_action === "approve_plan"} />)}
      {run.status === "waiting_approval" && run.plan && <PlanAdjustmentForm busy={busy} onSubmit={replan} />}
      {run.pending_action === "select_candidate" && (
        run.candidates.length === 2 && run.critique
          ? <CandidateCompare run={run} busy={busy} onSelect={decideCandidate} />
          : <StatusBanner tone="warning" message="候选证据正在恢复" detail="页面会继续读取 PostgreSQL 权威 Preview 和 Critic 结果。" />
      )}
      {(!terminal || !run.revision_id) && actions}
    </section>
  );
}

function actionKey(action: string): string { return `web-run-${action}-${crypto.randomUUID()}`; }

function message(error: unknown): string {
  if (error instanceof ApiError) return `${error.message}（${error.code}）`;
  if (error instanceof Error) return error.message;
  return "客户端发生未知错误";
}
