"""Safe read projection for the persisted Generate execution path."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from motif_forge.application.errors import ApplicationError
from motif_forge.application.run_graph_history import RunGraphHistoryStore
from motif_forge.application.run_graph_registry import (
    GENERATE_GRAPH_REGISTRY,
    GenerateGraphRegistry,
    GraphNodeKind,
    GraphRelation,
)
from motif_forge.application.run_inspection import RunInspectionFacts, RunInspectionStore
from motif_forge.domain.ai_runs import AIRunStatus

type EvidenceStatus = Literal["available", "partial", "unavailable"]
type ViewStatus = Literal["completed", "active", "waiting", "failed", "skipped", "not_visited"]
type NodeEvidence = Literal["checkpoint_confirmed", "event_confirmed", "grouped_parallel", "none"]
type EdgeStatus = Literal["traversed", "available", "not_visited"]


class RunGraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GraphPhaseView(RunGraphModel):
    id: str
    label: str
    status: ViewStatus
    summary: str
    node_ids: tuple[str, ...]
    collapsed_by_default: bool
    iteration_count: int = Field(ge=0)


class GraphNodeView(RunGraphModel):
    id: str
    phase_id: str
    label: str
    technical_name: str
    kind: GraphNodeKind
    status: ViewStatus
    evidence: NodeEvidence
    occurred_at: datetime | None
    iteration_count: int = Field(ge=0)
    default_visible: bool


class GraphEdgeView(RunGraphModel):
    source: str
    target: str
    relation: GraphRelation
    status: EdgeStatus


class GraphEvidenceSummary(RunGraphModel):
    checkpoint_count: int = Field(ge=0)
    task_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    human_decision_count: int = Field(ge=0)
    job_count: int = Field(ge=0)
    unmapped_task_count: int = Field(ge=0)
    truncated: bool
    schema_compatible: bool


class RunGraphReadModel(RunGraphModel):
    schema_version: Literal["run-graph-view.v1"] = "run-graph-view.v1"
    run_id: UUID
    graph_version: str
    graph_kind: Literal["generate"] = "generate"
    run_status: AIRunStatus
    evidence_status: EvidenceStatus
    current_phase_id: str | None
    phases: tuple[GraphPhaseView, ...]
    nodes: tuple[GraphNodeView, ...]
    edges: tuple[GraphEdgeView, ...]
    evidence_summary: GraphEvidenceSummary


_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "rejected"})
_EVENT_NODE_MAP = {
    "candidate.critic.completed": "critic:evaluate",
    "candidate.repair.applied": "critic:repair",
    "composition.candidate-selected": "commit:selection",
    "composition.materialized": "commit:materialize-selected",
}


def _current_phase(facts: RunInspectionFacts) -> str | None:
    status = facts.run.status
    latest_phase = facts.timeline[-1].phase if facts.timeline else ""
    if status in _TERMINAL:
        return None
    if status == "waiting_approval":
        return "approval"
    if latest_phase == "waiting_candidate_selection":
        return "commit"
    if "candidate" in latest_phase or "preview" in latest_phase:
        return "candidates"
    if "critic" in latest_phase or "repair" in latest_phase:
        return "critic"
    if status == "materializing" or "material" in latest_phase:
        return "commit"
    if status == "waiting_worker" or "export" in latest_phase:
        return "export"
    return "planning"


def _phase_summary(status: ViewStatus, confirmed: int, iterations: int) -> str:
    if status == "waiting":
        return "等待人工决定"
    if status == "active":
        return "正在执行"
    if status == "failed":
        return "执行失败。可查看最后证据"
    if status == "completed":
        suffix = f" (重复 {iterations} 次)" if iterations > 1 else ""
        return f"已确认 {confirmed} 个节点{suffix}"
    if status == "skipped":
        return "本次运行未选择该路线"
    return "尚未访问"


class ReadRunGraph:
    def __init__(
        self,
        inspection_store: RunInspectionStore,
        history_store: RunGraphHistoryStore,
        registry: GenerateGraphRegistry = GENERATE_GRAPH_REGISTRY,
    ) -> None:
        self._inspection_store = inspection_store
        self._history_store = history_store
        self._registry = registry

    async def __call__(self, run_id: UUID) -> RunGraphReadModel:
        facts = await self._inspection_store.read_run_inspection(run_id)
        if facts is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI Run does not exist")
        if facts.run.run_type != "generate":
            raise ApplicationError(
                "RUN_GRAPH_UNSUPPORTED",
                "the checkpoint graph view currently supports Generate Runs only",
            )
        history = await self._history_store.read_run_graph_history(facts.run.thread_id)
        current_phase = _current_phase(facts)

        counts: Counter[str] = Counter()
        candidate_paths = []
        registered_names = {node.technical_name for node in self._registry.nodes}
        unmapped = 0
        for item in history.task_paths:
            if item.technical_name not in registered_names:
                unmapped += 1
                continue
            if item.technical_name == "CreateCandidateBranch":
                candidate_paths.append(item)
            else:
                counts[item.technical_name] += 1

        event_times: dict[str, datetime] = {}
        for event in facts.timeline:
            node_id = _EVENT_NODE_MAP.get(event.event_type)
            if node_id is not None:
                event_times[node_id] = event.created_at

        candidate_counts = {
            "candidates:candidate-a": 1 if len(candidate_paths) >= 1 else 0,
            "candidates:candidate-b": 1 if len(candidate_paths) >= 2 else 0,
        }
        terminal = facts.run.status in _TERMINAL
        nodes: list[GraphNodeView] = []
        for definition in self._registry.nodes:
            count = candidate_counts.get(definition.id, counts.get(definition.technical_name, 0))
            evidence: NodeEvidence = "none"
            status: ViewStatus = "not_visited"
            if count:
                evidence = (
                    "grouped_parallel"
                    if definition.technical_name == "CreateCandidateBranch"
                    else "checkpoint_confirmed"
                )
                status = "completed"
            elif definition.id in event_times:
                evidence = "event_confirmed"
                status = "completed"

            is_human_wait = (
                facts.run.status == "waiting_approval" and definition.id == "approval:plan"
            ) or (
                facts.timeline
                and facts.timeline[-1].phase == "waiting_candidate_selection"
                and definition.id == "commit:selection"
            )
            if is_human_wait:
                status = "waiting"
                evidence = "event_confirmed" if evidence == "none" else evidence
            elif current_phase == definition.phase_id and status == "not_visited":
                phase_definitions = [
                    node for node in self._registry.nodes if node.phase_id == current_phase
                ]
                first_visible = next(
                    (node for node in phase_definitions if node.default_visible),
                    phase_definitions[0],
                )
                if definition.id == first_visible.id:
                    status = "active"

            if terminal and status == "not_visited":
                if definition.id in {
                    "commit:materialize-selected",
                    "commit:materialize-legacy",
                }:
                    selected_visited = counts.get("MaterializeSelectedCandidate", 0) > 0
                    legacy_visited = counts.get("MaterializeApprovedComposition", 0) > 0
                    if selected_visited or legacy_visited:
                        status = "skipped"
                elif facts.run.status in {"cancelled", "rejected"} and definition.phase_id not in {
                    "planning",
                    "approval",
                }:
                    status = "skipped"

            if facts.run.status == "failed" and definition.technical_name == "RouteError" and count:
                status = "failed"

            nodes.append(
                GraphNodeView(
                    id=definition.id,
                    phase_id=definition.phase_id,
                    label=definition.label,
                    technical_name=definition.technical_name,
                    kind=definition.kind,
                    status=status,
                    evidence=evidence,
                    occurred_at=event_times.get(definition.id),
                    iteration_count=count,
                    default_visible=definition.default_visible,
                )
            )

        node_by_id = {node.id: node for node in nodes}
        phases: list[GraphPhaseView] = []
        for phase_definition in self._registry.phases:
            phase_nodes = [node for node in nodes if node.phase_id == phase_definition.id]
            statuses = {node.status for node in phase_nodes}
            if "failed" in statuses:
                phase_status: ViewStatus = "failed"
            elif "waiting" in statuses:
                phase_status = "waiting"
            elif current_phase == phase_definition.id and not terminal:
                phase_status = "active"
            elif "completed" in statuses:
                phase_status = "completed"
            elif terminal and statuses == {"skipped"}:
                phase_status = "skipped"
            else:
                phase_status = "not_visited"
            confirmed = sum(node.evidence != "none" for node in phase_nodes)
            iterations = max((node.iteration_count for node in phase_nodes), default=0)
            phases.append(
                GraphPhaseView(
                    id=phase_definition.id,
                    label=phase_definition.label,
                    status=phase_status,
                    summary=_phase_summary(phase_status, confirmed, iterations),
                    node_ids=tuple(node.id for node in phase_nodes),
                    collapsed_by_default=phase_definition.collapsed_by_default,
                    iteration_count=iterations,
                )
            )

        edges: list[GraphEdgeView] = []
        for edge_definition in self._registry.edges:
            source = node_by_id[edge_definition.source]
            target = node_by_id[edge_definition.target]
            if target.evidence != "none" and source.status != "not_visited":
                edge_status: EdgeStatus = "traversed"
            elif source.evidence != "none" or source.status in {"active", "waiting"}:
                edge_status = "available"
            else:
                edge_status = "not_visited"
            edges.append(
                GraphEdgeView(
                    source=edge_definition.source,
                    target=edge_definition.target,
                    relation=edge_definition.relation,
                    status=edge_status,
                )
            )

        if not history.task_paths and history.schema_compatible:
            evidence_status: EvidenceStatus = "unavailable"
        elif history.truncated or not history.schema_compatible or unmapped:
            evidence_status = "partial"
        else:
            evidence_status = "available"

        return RunGraphReadModel(
            run_id=facts.run.run_id,
            graph_version=facts.versions.graph_topology_version,
            run_status=AIRunStatus(facts.run.status),
            evidence_status=evidence_status,
            current_phase_id=current_phase,
            phases=tuple(phases),
            nodes=tuple(nodes),
            edges=tuple(edges),
            evidence_summary=GraphEvidenceSummary(
                checkpoint_count=history.checkpoint_count,
                task_count=len(history.task_paths),
                event_count=len(facts.timeline),
                human_decision_count=len(facts.decisions),
                job_count=len(facts.jobs),
                unmapped_task_count=unmapped,
                truncated=history.truncated,
                schema_compatible=history.schema_compatible,
            ),
        )
