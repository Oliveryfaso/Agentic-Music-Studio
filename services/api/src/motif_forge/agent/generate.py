"""Generate branch nodes mounted into the single versioned Parent Graph."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from langgraph.types import interrupt
from pydantic import Field

from motif_forge.agent.critic import CriticCandidate, CriticRequest, EvidenceCritic
from motif_forge.agent.planner import CompositionPlanner
from motif_forge.agent.planning_subgraph import (
    build_composition_planning_subgraph,
    initial_planning_state,
)
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, PlanningResult
from motif_forge.application.ai_runs import RecordAIRunApproval
from motif_forge.application.candidate_previews import (
    CandidatePreviewCursor,
    EnqueueCandidatePreviewRequest,
)
from motif_forge.application.candidate_repair import (
    BoundedRepairRequest,
    EvaluateCandidatePair,
    MeasuredCandidateEvidence,
)
from motif_forge.application.errors import ApplicationError
from motif_forge.application.generation import (
    CollectCompleteExportArtifact,
    CompleteExportCursor,
    EnqueueNextCompleteExportJob,
    MaterializeApprovedComposition,
    MaterializeApprovedCompositionRequest,
    PersistPlanningResult,
    PersistPlanningResultRequest,
)
from motif_forge.application.generation_candidates import (
    CreateCandidateSelectionPreviewRequest,
    CreateCompositionCandidateRequest,
    MaterializeSelectedCompositionCandidateRequest,
)
from motif_forge.domain.candidates import (
    CandidateEvidence,
    CandidateLabel,
    derive_candidate_seed,
)
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import WorkerResumePayload
from motif_forge.domain.style_packs import builtin_style_pack_registry
from motif_forge.observability.models import TelemetryRecorder

PARENT_GRAPH_TOPOLOGY_VERSION = "motif-forge-parent.v2"
PARENT_STATE_SCHEMA_VERSION = "motif-forge-parent-state.v2"


class GenerateRequest(DomainModel):
    """Finite identities and bounded user input needed to start generation."""

    run_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    brief: CompositionBrief
    seed: int = Field(ge=0, le=2**31 - 1)
    expected_run_version: int = Field(default=0, ge=0)


class PlanApprovalDecision(DomainModel):
    decision: Literal["approve", "reject"]
    actor_id: str = Field(min_length=1, max_length=160)
    approval_assertion: str = Field(min_length=16, max_length=500)
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(default="", max_length=500)


class CandidateSelectionDecision(DomainModel):
    decision: Literal["select", "reject"]
    actor_id: str = Field(min_length=1, max_length=160)
    selection_assertion: str = Field(min_length=16, max_length=500)
    selected_preview_id: UUID | None = None
    expected_candidate_id: UUID | None = None
    expected_candidate_content_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    note: str = Field(default="", max_length=500)

    def model_post_init(self, __context: object) -> None:
        del __context
        values = (
            self.selected_preview_id,
            self.expected_candidate_id,
            self.expected_candidate_content_hash,
        )
        if self.decision == "select" and any(item is None for item in values):
            raise ValueError("candidate selection requires complete Preview identity")
        if self.decision == "reject" and any(item is not None for item in values):
            raise ValueError("candidate rejection forbids selected Preview identity")


class PlanningPersister(Protocol):
    async def __call__(self, request: PersistPlanningResultRequest) -> Any: ...


class ApprovalRecorder(Protocol):
    async def __call__(
        self,
        *,
        run_id: UUID,
        actor_id: str,
        decision: str,
        assertion: str,
        expected_version: int,
        expected_plan_content_hash: str,
        interrupt_ref: str,
    ) -> Any: ...


class CompositionMaterializer(Protocol):
    async def __call__(self, request: MaterializeApprovedCompositionRequest) -> Any: ...


ExportEnqueuer = Callable[[CompleteExportCursor], Awaitable[CompleteExportCursor]]
ExportCollector = Callable[..., Awaitable[CompleteExportCursor]]
CandidateCreator = Callable[[CreateCompositionCandidateRequest], Awaitable[Any]]
CandidatePreviewEnqueuer = Callable[[EnqueueCandidatePreviewRequest], Awaitable[Any]]
CandidatePreviewCollector = Callable[[CandidatePreviewCursor, UUID], Awaitable[Any]]
SelectionPreviewCreator = Callable[[CreateCandidateSelectionPreviewRequest], Awaitable[Any]]
SelectedCandidateMaterializer = Callable[
    [MaterializeSelectedCompositionCandidateRequest], Awaitable[Any]
]
CandidateEvidenceMeasurer = Callable[[UUID], Awaitable[MeasuredCandidateEvidence]]
CandidateRepairer = Callable[[BoundedRepairRequest], Awaitable[Any]]


def initial_generate_state(*, thread_id: str, request: GenerateRequest) -> dict[str, Any]:
    """Create compact Parent v2 state for one finite generate operation."""

    if not thread_id or len(thread_id) > 160:
        raise ValueError("thread_id must contain between 1 and 160 characters")
    return {
        "thread_id": thread_id,
        "run_id": str(request.run_id),
        "project_id": str(request.project_id),
        "branch_id": str(request.branch_id),
        "base_revision_id": str(request.base_revision_id),
        "operation": "generate",
        "graph_topology_version": PARENT_GRAPH_TOPOLOGY_VERSION,
        "state_schema_version": PARENT_STATE_SCHEMA_VERSION,
        "request_payload": {
            "brief": request.brief.model_dump(mode="json"),
            "seed": request.seed,
            "expected_run_version": request.expected_run_version,
        },
        "phase": "received",
        "artifact_refs": [],
    }


def _plan_summary(plan: CompositionPlan) -> dict[str, object]:
    return {
        "genre": plan.genre,
        "duration_bars": plan.duration_bars,
        "bpm": plan.bpm,
        "meter": plan.meter,
        "section_names": [section.name for section in plan.sections],
        "instrument_names": [item.name for item in plan.instrumentation],
    }


class GenerateNodes:
    """Deterministic adapters and side-effect owners for Parent generation."""

    def __init__(
        self,
        planner: CompositionPlanner,
        *,
        persist_planning_result: PlanningPersister,
        record_plan_approval: ApprovalRecorder,
        materialize_approved_composition: CompositionMaterializer,
        enqueue_next_complete_export_job: ExportEnqueuer,
        collect_complete_export_artifact: ExportCollector,
        create_composition_candidate: CandidateCreator | None = None,
        enqueue_candidate_preview: CandidatePreviewEnqueuer | None = None,
        collect_candidate_preview: CandidatePreviewCollector | None = None,
        evidence_critic: EvidenceCritic | None = None,
        create_candidate_selection_preview: SelectionPreviewCreator | None = None,
        materialize_selected_candidate: SelectedCandidateMaterializer | None = None,
        measure_candidate_evidence: CandidateEvidenceMeasurer | None = None,
        apply_candidate_repair: CandidateRepairer | None = None,
        candidate_quality_gate: EvaluateCandidatePair | None = None,
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        self._planning = build_composition_planning_subgraph(planner, telemetry=telemetry)
        self._persist = persist_planning_result
        self._record_approval = record_plan_approval
        self._materialize = materialize_approved_composition
        self._enqueue_export = enqueue_next_complete_export_job
        self._collect_export = collect_complete_export_artifact
        candidate_services = (
            create_composition_candidate,
            enqueue_candidate_preview,
            collect_candidate_preview,
            evidence_critic,
            create_candidate_selection_preview,
            materialize_selected_candidate,
        )
        if any(item is not None for item in candidate_services) and not all(
            item is not None for item in candidate_services
        ):
            raise ValueError("S5 candidate Graph services must be configured together")
        self._create_candidate = create_composition_candidate
        self._enqueue_candidate_preview = enqueue_candidate_preview
        self._collect_candidate_preview = collect_candidate_preview
        self._critic = evidence_critic
        self._create_selection_preview = create_candidate_selection_preview
        self._materialize_selected = materialize_selected_candidate
        repair_services = (
            measure_candidate_evidence,
            apply_candidate_repair,
            candidate_quality_gate,
        )
        if any(item is not None for item in repair_services) and not all(
            item is not None for item in repair_services
        ):
            raise ValueError("S5 Repair Graph services must be configured together")
        self._measure_evidence = measure_candidate_evidence
        self._apply_repair = apply_candidate_repair
        self._quality_gate = candidate_quality_gate

    @property
    def candidate_flow_enabled(self) -> bool:
        return self._create_candidate is not None

    async def validate_generate(self, state: Any) -> dict[str, Any]:
        try:
            request = GenerateRequest.model_validate_json(
                json.dumps(
                    {
                        "run_id": str(state["run_id"]),
                        "project_id": str(state["project_id"]),
                        "branch_id": str(state["branch_id"]),
                        "base_revision_id": str(state["base_revision_id"]),
                        "brief": state["request_payload"]["brief"],
                        "seed": state["request_payload"]["seed"],
                        "expected_run_version": state["request_payload"].get(
                            "expected_run_version", 0
                        ),
                    }
                ),
                strict=True,
            )
        except (KeyError, TypeError, ValueError):
            return {"phase": "failed", "error_code": "PARENT_REQUEST_INVALID"}
        if request.brief.meter != "4/4":
            return {"phase": "failed", "error_code": "GENERATE_STRATEGY_UNSUPPORTED"}
        return {"phase": "generate_validated"}

    async def plan_input_adapter(self, state: Any) -> dict[str, Any]:
        del state
        return {"phase": "planning"}

    async def plan_output_adapter(self, state: Any) -> dict[str, Any]:
        planning_result = cast(
            PlanningResult,
            await self._planning.ainvoke(
                initial_planning_state(
                    run_id=str(state["run_id"]),
                    thread_id=str(state["thread_id"]),
                    brief_payload=state["request_payload"]["brief"],
                )
            ),
        )
        if planning_result["phase"] != "planning_complete" or "plan" not in planning_result:
            error = planning_result.get("error", {})
            return {
                "phase": "failed",
                "error_code": str(error.get("code", "PLANNING_FAILED")),
                "model_counters": dict(planning_result["counters"]),
            }
        if planning_result.get("error") is None:
            planning_result.pop("error", None)
        persisted = await self._persist(
            PersistPlanningResultRequest(
                run_id=UUID(str(state["run_id"])),
                expected_run_version=int(state["request_payload"].get("expected_run_version", 0)),
                planning_result=planning_result,
                style_pack_version=builtin_style_pack_registry()
                .resolve(
                    CompositionPlan.model_validate_json(
                        json.dumps(planning_result["plan"]), strict=True
                    ).genre
                )
                .pack_id,
            )
        )
        plan = CompositionPlan.model_validate_json(json.dumps(planning_result["plan"]), strict=True)
        update: dict[str, Any] = {
            "phase": "waiting_plan_approval",
            "plan_id": str(persisted.plan_id),
            "plan_hash": persisted.plan_hash,
            "plan_summary": _plan_summary(plan),
            "plan_interrupt_ref": persisted.interrupt_ref,
            "run_version": persisted.run_version,
            "model_counters": dict(planning_result["counters"]),
        }
        if "fallback_reason" in planning_result:
            update["fallback_reason"] = planning_result["fallback_reason"]
        return update

    async def approval_interrupt(self, state: Any) -> dict[str, Any]:
        resumed = interrupt(
            {
                "kind": "plan_approval",
                "phase": "waiting_plan_approval",
                "plan_id": state["plan_id"],
                "plan_hash": state["plan_hash"],
                "summary": state["plan_summary"],
                "options": ["approve", "reject", "cancel"],
            }
        )
        if isinstance(resumed, Mapping) and resumed.get("action") == "cancel":
            return {"phase": "cancelled", "terminal_status": "cancelled"}
        try:
            decision = PlanApprovalDecision.model_validate(resumed, strict=True)
        except ValueError:
            return {"phase": "failed", "error_code": "PLAN_APPROVAL_INVALID"}
        if decision.expected_plan_hash != state["plan_hash"]:
            return {"phase": "failed", "error_code": "PLAN_HASH_MISMATCH"}
        await self._record_approval(
            run_id=UUID(str(state["run_id"])),
            actor_id=decision.actor_id,
            decision=decision.decision,
            assertion=decision.approval_assertion,
            expected_version=int(state["run_version"]),
            expected_plan_content_hash=decision.expected_plan_hash,
            interrupt_ref=str(state["plan_interrupt_ref"]),
        )
        if decision.decision == "reject":
            return {
                "phase": "rejected",
                "terminal_status": "rejected",
                "approval_decision": "reject",
                "approval_actor_id": decision.actor_id,
                "approval_note": decision.note,
            }
        return {
            "phase": "approved",
            "approval_decision": "approve",
            "approval_actor_id": decision.actor_id,
            "approval_assertion": decision.approval_assertion,
            "approval_note": decision.note,
        }

    async def materialize(self, state: Any) -> dict[str, Any]:
        result = await self._materialize(
            MaterializeApprovedCompositionRequest(
                run_id=UUID(str(state["run_id"])),
                project_id=UUID(str(state["project_id"])),
                branch_id=UUID(str(state["branch_id"])),
                base_revision_id=UUID(str(state["base_revision_id"])),
                plan_id=UUID(str(state["plan_id"])),
                expected_plan_hash=str(state["plan_hash"]),
                seed=int(state["request_payload"]["seed"]),
                actor_id=str(state["approval_actor_id"]),
                approval_assertion=str(state["approval_assertion"]),
                idempotency_key=f"generate-materialize:{state['run_id']}",
            )
        )
        if result.status != "approved" or result.revision_id is None:
            return {"phase": "failed", "error_code": "MATERIALIZATION_FAILED"}
        cursor = CompleteExportCursor(
            project_id=UUID(str(state["project_id"])),
            revision_id=result.revision_id,
            thread_id=str(state["thread_id"]),
            seed=int(state["request_payload"]["seed"]),
        )
        return {
            "phase": "revision_materialized",
            "materialized_revision_id": str(result.revision_id),
            "export_cursor": cursor.model_dump(mode="json"),
        }

    async def create_candidate_branch(self, state: Any) -> dict[str, Any]:
        assert self._create_candidate is not None
        label = CandidateLabel(str(state["candidate_label"]))
        seed = derive_candidate_seed(int(state["request_payload"]["seed"]), label)
        result = await self._create_candidate(
            CreateCompositionCandidateRequest(
                run_id=UUID(str(state["run_id"])),
                project_id=UUID(str(state["project_id"])),
                branch_id=UUID(str(state["branch_id"])),
                base_revision_id=UUID(str(state["base_revision_id"])),
                plan_id=UUID(str(state["plan_id"])),
                expected_plan_hash=str(state["plan_hash"]),
                label=label,
                seed=seed,
            )
        )
        return {
            "candidate_branches": [
                {
                    "candidate_id": str(result.candidate_id),
                    "label": label.value,
                    "seed": seed,
                    "candidate_snapshot_id": str(result.candidate_snapshot_id),
                    "latest_snapshot_id": str(result.candidate_snapshot_id),
                    "candidate_content_hash": result.candidate_content_hash,
                    "style_pack_version": result.style_pack_version,
                    "compiler_version": result.compiler_version,
                    "repair_status": "not_requested",
                }
            ]
        }

    async def candidate_fan_in(self, state: Any) -> dict[str, Any]:
        branches = sorted(state["candidate_branches"], key=lambda item: item["label"])
        if [item["label"] for item in branches] != ["a", "b"]:
            return {"phase": "failed", "error_code": "CANDIDATE_FAN_IN_INVALID"}
        return {"phase": "generating_candidates", "candidate_working": branches}

    async def enqueue_candidate_preview(self, state: Any) -> dict[str, Any]:
        assert self._enqueue_candidate_preview is not None
        pending = next(
            (
                item
                for item in state["candidate_working"]
                if item.get("preview_artifact_id") is None
            ),
            None,
        )
        if pending is None:
            return {"phase": "candidate_previews_ready"}
        cursor = await self._enqueue_candidate_preview(
            EnqueueCandidatePreviewRequest(
                project_id=UUID(str(state["project_id"])),
                candidate_snapshot_id=UUID(str(pending["latest_snapshot_id"])),
                expected_candidate_content_hash=str(pending["candidate_content_hash"]),
                thread_id=str(state["thread_id"]),
                seed=int(pending["seed"]),
                idempotency_key=(
                    f"candidate-preview:{state['run_id']}:{pending['candidate_id']}:"
                    f"{pending['latest_snapshot_id']}"
                ),
            )
        )
        return {
            "phase": "rendering_candidate_previews",
            "candidate_preview_cursor": cursor.model_dump(mode="json"),
            "pending_job_id": str(cursor.job_id),
            "media_run_id": str(cursor.media_run_id),
        }

    async def wait_for_candidate_preview(self, state: Any) -> dict[str, Any]:
        assert self._collect_candidate_preview is not None
        resumed = interrupt(
            {
                "kind": "worker_job",
                "phase": "rendering_candidate_previews",
                "job_id": state["pending_job_id"],
            }
        )
        try:
            payload = WorkerResumePayload.model_validate_json(
                json.dumps(resumed, default=str), strict=True
            )
        except ValueError:
            return {"phase": "failed", "error_code": "WORKER_RESUME_INVALID"}
        if (
            str(payload.job_id) != state["pending_job_id"]
            or str(payload.run_id) != state["media_run_id"]
            or payload.thread_id != state["thread_id"]
        ):
            return {"phase": "failed", "error_code": "WORKER_RESUME_MISMATCH"}
        if payload.status == "failed_terminal":
            return {
                "phase": "failed",
                "error_code": payload.error_code or "CANDIDATE_PREVIEW_FAILED",
            }
        cursor = CandidatePreviewCursor.model_validate_json(
            json.dumps(state["candidate_preview_cursor"]), strict=True
        )
        try:
            completed = await self._collect_candidate_preview(cursor, payload.job_id)
        except ApplicationError as exc:
            return {"phase": "failed", "error_code": exc.code}
        branches = [dict(item) for item in state["candidate_working"]]
        branch = next(
            item
            for item in branches
            if item["latest_snapshot_id"] == str(completed.candidate_snapshot_id)
        )
        branch["preview_artifact_id"] = str(completed.preview_artifact_id)
        return {
            "phase": "candidate_preview_collected",
            "candidate_working": branches,
            "candidate_preview_cursor": None,
            "pending_job_id": None,
            "last_resume_event_id": payload.resume_event_id,
        }

    async def criticize_candidates(self, state: Any) -> dict[str, Any]:
        assert self._critic is not None
        candidates = tuple(
            CriticCandidate(
                candidate_id=UUID(str(item["candidate_id"])),
                label=CandidateLabel(str(item["label"])),
            )
            for item in state["candidate_working"]
        )
        measurements: list[dict[str, Any]] = []
        if self._measure_evidence is not None:
            measured = tuple(
                [
                    await self._measure_evidence(UUID(str(item["latest_snapshot_id"])))
                    for item in state["candidate_working"]
                ]
            )
            evidence = tuple(item.evidence for item in measured)
            measurements = [item.model_dump(mode="json") for item in measured]
        else:
            evidence = tuple(
                CandidateEvidence(
                    evidence_ref=f"candidate:{item['candidate_id']}:preview",
                    candidate_id=UUID(str(item["candidate_id"])),
                    kind="audio",
                    severity="info",
                    measured_fact="authoritative full-length candidate Preview is available",
                    score_delta=0,
                )
                for item in state["candidate_working"]
            )
        result = await self._critic.evaluate(
            CriticRequest(
                run_id=UUID(str(state["run_id"])),
                candidates=candidates,
                evidence=evidence,
            )
        )
        return {
            "phase": "critic_complete",
            "critique": result.critique.model_dump(mode="json"),
            "critic_provider": result.provider,
            "critic_model_calls": result.model_calls,
            "candidate_measurements": measurements,
        }

    async def apply_critic_repair(self, state: Any) -> dict[str, Any]:
        proposal = state["critique"].get("repair_proposal")
        if (
            proposal is None
            or self._apply_repair is None
            or self._measure_evidence is None
            or self._quality_gate is None
        ):
            return {"phase": "repair_complete", "repair_count": 0}
        measurement = next(
            (
                MeasuredCandidateEvidence.model_validate_json(
                    json.dumps(item), strict=True
                )
                for item in state["candidate_measurements"]
                if item["segment"]["segment_id"] == proposal["segment_id"]
            ),
            None,
        )
        branch = next(
            (
                item
                for item in state["candidate_working"]
                if item["candidate_id"] == proposal["candidate_id"]
            ),
            None,
        )
        if measurement is None or branch is None:
            return {"phase": "failed", "error_code": "CANDIDATE_REPAIR_EVIDENCE_INVALID"}
        cited = tuple(
            item
            for item in state["critique"]["evidence"]
            if item["evidence_ref"] in proposal["evidence_refs"]
        )
        result = await self._apply_repair(
            BoundedRepairRequest(
                run_id=UUID(str(state["run_id"])),
                project_id=UUID(str(state["project_id"])),
                parent_candidate_snapshot_id=UUID(str(branch["latest_snapshot_id"])),
                segment=measurement.segment,
                operation=proposal["operation"],
                evidence=tuple(
                    CandidateEvidence.model_validate_json(json.dumps(item), strict=True)
                    for item in cited
                ),
                evidence_refs=tuple(proposal["evidence_refs"]),
            )
        )
        repaired = await self._measure_evidence(result.child_snapshot_id)
        original_score = next(
            int(item["score"])
            for item in state["critique"]["assessments"]
            if item["candidate_id"] == branch["candidate_id"]
        )
        repaired_score = max(0, min(100, 75 + repaired.evidence.score_delta))
        decision = self._quality_gate(
            original_snapshot_id=UUID(str(branch["latest_snapshot_id"])),
            repaired_snapshot_id=result.child_snapshot_id,
            original_score=original_score,
            repaired_score=repaired_score,
            original_blocking_errors=0,
            repaired_blocking_errors=0,
        )
        await self._quality_gate.record(
            run_id=UUID(str(state["run_id"])), decision=decision
        )
        branches = [dict(item) for item in state["candidate_working"]]
        changed = next(item for item in branches if item["candidate_id"] == branch["candidate_id"])
        changed["repair_status"] = decision.repair_status
        changed["score"] = (
            repaired_score if decision.repair_status == "improved" else original_score
        )
        if decision.repair_status == "improved":
            changed["latest_snapshot_id"] = str(result.child_snapshot_id)
            changed["candidate_content_hash"] = result.candidate_content_hash
            changed["preview_artifact_id"] = None
            return {
                "phase": "repair_preview_required",
                "candidate_working": branches,
                "repair_count": 1,
            }
        return {
            "phase": "repair_complete",
            "candidate_working": branches,
            "repair_count": 1,
        }

    async def create_selection_previews(self, state: Any) -> dict[str, Any]:
        assert self._create_selection_preview is not None
        critique = state["critique"]
        refs_by_candidate = {
            str(item["candidate_id"]): tuple(item["evidence_refs"])
            for item in critique["assessments"]
        }
        branches = [dict(item) for item in state["candidate_working"]]
        for item in branches:
            result = await self._create_selection_preview(
                CreateCandidateSelectionPreviewRequest(
                    run_id=UUID(str(state["run_id"])),
                    project_id=UUID(str(state["project_id"])),
                    branch_id=UUID(str(state["branch_id"])),
                    base_revision_id=UUID(str(state["base_revision_id"])),
                    candidate_snapshot_id=UUID(str(item["latest_snapshot_id"])),
                    preview_artifact_id=UUID(str(item["preview_artifact_id"])),
                    evidence_refs=refs_by_candidate[str(item["candidate_id"])],
                )
            )
            item["selection_preview_id"] = str(result.preview_id)
        return {"phase": "waiting_candidate_selection", "candidate_working": branches}

    async def candidate_selection_interrupt(self, state: Any) -> dict[str, Any]:
        resumed = interrupt(
            {
                "kind": "candidate_selection",
                "phase": "waiting_candidate_selection",
                "candidates": state["candidate_working"],
                "critique": state["critique"],
                "options": ["select", "reject", "cancel"],
            }
        )
        if isinstance(resumed, Mapping) and resumed.get("action") == "cancel":
            return {"phase": "cancelled", "terminal_status": "cancelled"}
        try:
            decision = CandidateSelectionDecision.model_validate_json(
                json.dumps(resumed, default=str), strict=True
            )
        except ValueError:
            return {"phase": "failed", "error_code": "CANDIDATE_SELECTION_INVALID"}
        if decision.decision == "reject":
            return {"phase": "rejected", "terminal_status": "rejected"}
        selected = next(
            (
                item
                for item in state["candidate_working"]
                if item["selection_preview_id"] == str(decision.selected_preview_id)
            ),
            None,
        )
        if (
            selected is None
            or selected["candidate_id"] != str(decision.expected_candidate_id)
            or selected["candidate_content_hash"]
            != decision.expected_candidate_content_hash
        ):
            return {"phase": "failed", "error_code": "CANDIDATE_SELECTION_MISMATCH"}
        return {
            "phase": "candidate_selected",
            "selected_candidate_id": selected["candidate_id"],
            "selected_candidate_snapshot_id": selected["latest_snapshot_id"],
            "selected_preview_id": selected["selection_preview_id"],
            "selected_candidate_content_hash": selected["candidate_content_hash"],
            "selection_actor_id": decision.actor_id,
            "selection_assertion": decision.selection_assertion,
            "selection_note": decision.note,
            "selected_seed": selected["seed"],
        }

    async def materialize_selected_candidate(self, state: Any) -> dict[str, Any]:
        assert self._materialize_selected is not None
        result = await self._materialize_selected(
            MaterializeSelectedCompositionCandidateRequest(
                run_id=UUID(str(state["run_id"])),
                project_id=UUID(str(state["project_id"])),
                branch_id=UUID(str(state["branch_id"])),
                base_revision_id=UUID(str(state["base_revision_id"])),
                plan_id=UUID(str(state["plan_id"])),
                expected_plan_hash=str(state["plan_hash"]),
                selected_preview_id=UUID(str(state["selected_preview_id"])),
                expected_candidate_content_hash=str(
                    state["selected_candidate_content_hash"]
                ),
                seed=int(state["selected_seed"]),
                actor_id=str(state["selection_actor_id"]),
                selection_assertion=str(state["selection_assertion"]),
                idempotency_key=f"candidate-selection:{state['run_id']}",
            )
        )
        cursor = CompleteExportCursor(
            project_id=UUID(str(state["project_id"])),
            revision_id=result.revision_id,
            thread_id=str(state["thread_id"]),
            seed=int(state["selected_seed"]),
        )
        return {
            "phase": "revision_materialized",
            "materialized_revision_id": str(result.revision_id),
            "export_cursor": cursor.model_dump(mode="json"),
        }

    @staticmethod
    def _cursor(value: object) -> CompleteExportCursor:
        return CompleteExportCursor.model_validate_json(json.dumps(value), strict=True)

    async def enqueue_export(self, state: Any) -> dict[str, Any]:
        cursor = self._cursor(state["export_cursor"])
        cursor = await self._enqueue_export(cursor)
        return {
            "phase": "waiting_generate_worker" if cursor.pending_job_id else "completed",
            "export_cursor": cursor.model_dump(mode="json"),
            "media_run_id": str(cursor.media_run_id) if cursor.media_run_id else None,
            "pending_job_id": str(cursor.pending_job_id) if cursor.pending_job_id else None,
            "artifact_refs": [
                *(str(item) for item in cursor.audio_artifact_ids),
                *([str(cursor.bundle_artifact_id)] if cursor.bundle_artifact_id else []),
            ],
        }

    async def wait_for_export(self, state: Any) -> dict[str, Any]:
        resumed = interrupt(
            {
                "kind": "worker_job",
                "phase": "waiting_generate_worker",
                "job_id": state["pending_job_id"],
            }
        )
        try:
            payload = WorkerResumePayload.model_validate_json(
                json.dumps(resumed, default=str), strict=True
            )
        except ValueError:
            return {"phase": "failed", "error_code": "WORKER_RESUME_INVALID"}
        if payload.resume_event_id and payload.resume_event_id == state.get("last_resume_event_id"):
            return {"phase": "waiting_generate_worker"}
        if (
            str(payload.job_id) != state["pending_job_id"]
            or str(payload.run_id) != state["media_run_id"]
            or payload.thread_id != state["thread_id"]
        ):
            return {"phase": "failed", "error_code": "WORKER_RESUME_MISMATCH"}
        if payload.status == "failed_terminal":
            return {
                "phase": "failed",
                "error_code": payload.error_code or "WORKER_TERMINAL_FAILURE",
                "last_resume_event_id": payload.resume_event_id,
            }
        cursor = self._cursor(state["export_cursor"])
        try:
            cursor = await self._collect_export(cursor, completed_job_id=payload.job_id)
        except ApplicationError as exc:
            return {
                "phase": "failed",
                "error_code": exc.code,
                "last_resume_event_id": payload.resume_event_id,
            }
        return {
            "phase": "export_step_collected",
            "export_cursor": cursor.model_dump(mode="json"),
            "pending_job_id": None,
            "last_resume_event_id": payload.resume_event_id,
            "artifact_refs": [
                *(str(item) for item in cursor.audio_artifact_ids),
                *([str(cursor.bundle_artifact_id)] if cursor.bundle_artifact_id else []),
            ],
        }

    async def complete(self, state: Any) -> dict[str, Any]:
        cursor = self._cursor(state["export_cursor"])
        if cursor.pending_steps or cursor.bundle_artifact_id is None:
            return {"phase": "failed", "error_code": "EXPORT_INCOMPLETE"}
        return {"phase": "completed", "terminal_status": "succeeded"}


def build_generate_nodes(
    planner: CompositionPlanner,
    *,
    persist_planning_result: PersistPlanningResult,
    record_plan_approval: RecordAIRunApproval,
    materialize_approved_composition: MaterializeApprovedComposition,
    enqueue_next_complete_export_job: EnqueueNextCompleteExportJob,
    collect_complete_export_artifact: CollectCompleteExportArtifact,
    create_composition_candidate: CandidateCreator | None = None,
    enqueue_candidate_preview: CandidatePreviewEnqueuer | None = None,
    collect_candidate_preview: CandidatePreviewCollector | None = None,
    evidence_critic: EvidenceCritic | None = None,
    create_candidate_selection_preview: SelectionPreviewCreator | None = None,
    materialize_selected_candidate: SelectedCandidateMaterializer | None = None,
    measure_candidate_evidence: CandidateEvidenceMeasurer | None = None,
    apply_candidate_repair: CandidateRepairer | None = None,
    candidate_quality_gate: EvaluateCandidatePair | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> GenerateNodes:
    return GenerateNodes(
        planner,
        persist_planning_result=persist_planning_result,
        record_plan_approval=record_plan_approval,
        materialize_approved_composition=materialize_approved_composition,
        enqueue_next_complete_export_job=enqueue_next_complete_export_job,
        collect_complete_export_artifact=collect_complete_export_artifact,
        create_composition_candidate=create_composition_candidate,
        enqueue_candidate_preview=enqueue_candidate_preview,
        collect_candidate_preview=collect_candidate_preview,
        evidence_critic=evidence_critic,
        create_candidate_selection_preview=create_candidate_selection_preview,
        materialize_selected_candidate=materialize_selected_candidate,
        measure_candidate_evidence=measure_candidate_evidence,
        apply_candidate_repair=apply_candidate_repair,
        candidate_quality_gate=candidate_quality_gate,
        telemetry=telemetry,
    )
