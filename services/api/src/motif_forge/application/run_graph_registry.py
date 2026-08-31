"""Static presentation metadata for the existing Generate Parent Graph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

type GraphNodeKind = Literal["deterministic", "agent", "human", "worker"]
type GraphRelation = Literal["sequence", "parallel", "join", "loop", "worker_boundary"]


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GraphPhaseDefinition(RegistryModel):
    id: str
    label: str
    order: int
    collapsed_by_default: bool = False


class GraphNodeDefinition(RegistryModel):
    id: str
    phase_id: str
    label: str
    technical_name: str
    kind: GraphNodeKind
    order: int
    default_visible: bool = True
    group_id: str | None = None


class GraphEdgeDefinition(RegistryModel):
    source: str
    target: str
    relation: GraphRelation = "sequence"


class GenerateGraphRegistry(RegistryModel):
    graph_version: str
    phases: tuple[GraphPhaseDefinition, ...]
    nodes: tuple[GraphNodeDefinition, ...]
    edges: tuple[GraphEdgeDefinition, ...]


def _node(
    node_id: str,
    phase: str,
    label: str,
    technical_name: str,
    kind: GraphNodeKind,
    order: int,
    *,
    visible: bool = True,
    group: str | None = None,
) -> GraphNodeDefinition:
    return GraphNodeDefinition(
        id=node_id,
        phase_id=phase,
        label=label,
        technical_name=technical_name,
        kind=kind,
        order=order,
        default_visible=visible,
        group_id=group,
    )


GENERATE_GRAPH_REGISTRY = GenerateGraphRegistry(
    graph_version="motif-forge-parent.v2",
    phases=(
        GraphPhaseDefinition(id="planning", label="理解与规划", order=1),
        GraphPhaseDefinition(id="approval", label="计划确认", order=2),
        GraphPhaseDefinition(id="candidates", label="候选生成", order=3),
        GraphPhaseDefinition(id="critic", label="证据审查", order=4),
        GraphPhaseDefinition(id="commit", label="选择与落版", order=5),
        GraphPhaseDefinition(id="export", label="完整导出", order=6),
        GraphPhaseDefinition(id="error", label="错误路由", order=7, collapsed_by_default=True),
    ),
    nodes=(
        _node(
            "planning:validate-request",
            "planning",
            "校验生成请求",
            "ValidateRequest",
            "deterministic",
            1,
        ),
        _node(
            "planning:input-adapter",
            "planning",
            "准备规划输入",
            "PlanInputAdapter",
            "deterministic",
            2,
            visible=False,
        ),
        _node(
            "planning:validate-brief",
            "planning",
            "校验创作简报",
            "ValidateBrief",
            "deterministic",
            3,
        ),
        _node("planning:compose", "planning", "规划曲式与编配", "CompositionPlanner", "agent", 4),
        _node(
            "planning:validate-plan", "planning", "验证音乐计划", "ValidatePlan", "deterministic", 5
        ),
        _node(
            "planning:repair-plan", "planning", "修复计划", "RepairPlan", "agent", 6, visible=False
        ),
        _node(
            "planning:error-router",
            "planning",
            "规划错误分流",
            "ErrorRouter",
            "deterministic",
            7,
            visible=False,
        ),
        _node(
            "planning:fallback",
            "planning",
            "确定性计划降级",
            "DeterministicPlanFallback",
            "deterministic",
            8,
            visible=False,
        ),
        _node(
            "planning:fallback-route",
            "planning",
            "选择降级路线",
            "PlanningFallbackRoute",
            "deterministic",
            9,
            visible=False,
        ),
        _node(
            "planning:terminal-router",
            "planning",
            "规划终态分流",
            "PlanningTerminalRouter",
            "deterministic",
            10,
            visible=False,
        ),
        _node(
            "planning:complete",
            "planning",
            "完成规划",
            "PlanningComplete",
            "deterministic",
            11,
            visible=False,
        ),
        _node(
            "planning:failed",
            "planning",
            "规划失败",
            "PlanningFailed",
            "deterministic",
            12,
            visible=False,
        ),
        _node(
            "planning:output-adapter",
            "planning",
            "返回计划结果",
            "PlanOutputAdapter",
            "deterministic",
            13,
            visible=False,
        ),
        _node("approval:plan", "approval", "审批创作计划", "PlanApproval", "human", 1),
        _node(
            "candidates:candidate-a",
            "candidates",
            "生成候选 A",
            "CreateCandidateBranch",
            "deterministic",
            1,
            group="candidate-pair",
        ),
        _node(
            "candidates:candidate-b",
            "candidates",
            "生成候选 B",
            "CreateCandidateBranch",
            "deterministic",
            2,
            group="candidate-pair",
        ),
        _node("candidates:fan-in", "candidates", "汇合候选", "CandidateFanIn", "deterministic", 3),
        _node(
            "candidates:enqueue-preview",
            "candidates",
            "请求候选试听",
            "EnqueueCandidatePreview",
            "worker",
            4,
        ),
        _node(
            "candidates:wait-preview",
            "candidates",
            "等待候选试听",
            "WaitForCandidatePreview",
            "worker",
            5,
        ),
        _node("critic:evaluate", "critic", "按证据审查候选", "CriticizeCandidates", "agent", 1),
        _node(
            "critic:repair", "critic", "应用一次有界修复", "ApplyCriticRepair", "deterministic", 2
        ),
        _node(
            "critic:selection-previews",
            "critic",
            "准备选择试听",
            "CreateCandidateSelectionPreviews",
            "worker",
            3,
        ),
        _node("commit:selection", "commit", "选择候选", "CandidateSelection", "human", 1),
        _node(
            "commit:materialize-selected",
            "commit",
            "物化已选作品",
            "MaterializeSelectedCandidate",
            "deterministic",
            2,
        ),
        _node(
            "commit:materialize-legacy",
            "commit",
            "物化已批计划",
            "MaterializeApprovedComposition",
            "deterministic",
            3,
            visible=False,
        ),
        _node(
            "commit:storage-gate",
            "commit",
            "检查导出空间",
            "StoragePressureGate",
            "deterministic",
            4,
        ),
        _node("export:enqueue", "export", "推进完整导出", "EnqueueCompleteExportStep", "worker", 1),
        _node("export:wait", "export", "等待导出任务", "WaitForGenerateJobEvent", "worker", 2),
        _node("export:complete", "export", "完成整曲生成", "CompleteGenerate", "deterministic", 3),
        _node(
            "error:route", "error", "路由运行错误", "RouteError", "deterministic", 1, visible=False
        ),
    ),
    edges=(
        GraphEdgeDefinition(source="planning:validate-request", target="planning:input-adapter"),
        GraphEdgeDefinition(source="planning:input-adapter", target="planning:validate-brief"),
        GraphEdgeDefinition(source="planning:validate-brief", target="planning:compose"),
        GraphEdgeDefinition(source="planning:compose", target="planning:validate-plan"),
        GraphEdgeDefinition(source="planning:validate-plan", target="planning:complete"),
        GraphEdgeDefinition(
            source="planning:validate-plan", target="planning:repair-plan", relation="loop"
        ),
        GraphEdgeDefinition(
            source="planning:repair-plan", target="planning:validate-plan", relation="loop"
        ),
        GraphEdgeDefinition(
            source="planning:validate-plan", target="planning:fallback", relation="loop"
        ),
        GraphEdgeDefinition(source="planning:complete", target="planning:output-adapter"),
        GraphEdgeDefinition(source="planning:output-adapter", target="approval:plan"),
        GraphEdgeDefinition(
            source="approval:plan", target="candidates:candidate-a", relation="parallel"
        ),
        GraphEdgeDefinition(
            source="approval:plan", target="candidates:candidate-b", relation="parallel"
        ),
        GraphEdgeDefinition(
            source="candidates:candidate-a", target="candidates:fan-in", relation="join"
        ),
        GraphEdgeDefinition(
            source="candidates:candidate-b", target="candidates:fan-in", relation="join"
        ),
        GraphEdgeDefinition(
            source="candidates:fan-in",
            target="candidates:enqueue-preview",
            relation="worker_boundary",
        ),
        GraphEdgeDefinition(
            source="candidates:enqueue-preview",
            target="candidates:wait-preview",
            relation="worker_boundary",
        ),
        GraphEdgeDefinition(
            source="candidates:wait-preview", target="candidates:enqueue-preview", relation="loop"
        ),
        GraphEdgeDefinition(source="candidates:enqueue-preview", target="critic:evaluate"),
        GraphEdgeDefinition(source="critic:evaluate", target="critic:repair"),
        GraphEdgeDefinition(
            source="critic:repair", target="candidates:enqueue-preview", relation="loop"
        ),
        GraphEdgeDefinition(source="critic:repair", target="critic:selection-previews"),
        GraphEdgeDefinition(
            source="critic:selection-previews",
            target="commit:selection",
            relation="worker_boundary",
        ),
        GraphEdgeDefinition(source="commit:selection", target="commit:materialize-selected"),
        GraphEdgeDefinition(source="approval:plan", target="commit:materialize-legacy"),
        GraphEdgeDefinition(source="commit:materialize-selected", target="commit:storage-gate"),
        GraphEdgeDefinition(source="commit:materialize-legacy", target="commit:storage-gate"),
        GraphEdgeDefinition(
            source="commit:storage-gate", target="export:enqueue", relation="worker_boundary"
        ),
        GraphEdgeDefinition(
            source="export:enqueue", target="export:wait", relation="worker_boundary"
        ),
        GraphEdgeDefinition(source="export:wait", target="export:enqueue", relation="loop"),
        GraphEdgeDefinition(source="export:enqueue", target="export:complete"),
    ),
)
