"""Generate branch nodes mounted into the single versioned Parent Graph."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from langgraph.types import interrupt
from pydantic import Field

from motif_forge.agent.planner import CompositionPlanner
from motif_forge.agent.planning_subgraph import (
    build_composition_planning_subgraph,
    initial_planning_state,
)
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, PlanningResult
from motif_forge.application.ai_runs import RecordAIRunApproval
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
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import WorkerResumePayload
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
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        self._planning = build_composition_planning_subgraph(planner, telemetry=telemetry)
        self._persist = persist_planning_result
        self._record_approval = record_plan_approval
        self._materialize = materialize_approved_composition
        self._enqueue_export = enqueue_next_complete_export_job
        self._collect_export = collect_complete_export_artifact

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
        if request.brief.style != "synth_ambient" or request.brief.meter != "4/4":
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
                expected_run_version=int(
                    state["request_payload"].get("expected_run_version", 0)
                ),
                planning_result=planning_result,
            )
        )
        plan = CompositionPlan.model_validate_json(
            json.dumps(planning_result["plan"]), strict=True
        )
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
    telemetry: TelemetryRecorder | None = None,
) -> GenerateNodes:
    return GenerateNodes(
        planner,
        persist_planning_result=persist_planning_result,
        record_plan_approval=record_plan_approval,
        materialize_approved_composition=materialize_approved_composition,
        enqueue_next_complete_export_job=enqueue_next_complete_export_job,
        collect_complete_export_artifact=collect_complete_export_artifact,
        telemetry=telemetry,
    )
