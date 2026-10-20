"""Persistent manual piano audition, exact approval and explicit study entry."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from types import SimpleNamespace
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Header
from langgraph.types import Command
from motif_forge.agent.parent_graph import initial_piano_preview_state
from motif_forge.application.ai_runs import ReadAIRun, ReadAIRunByThreadId, RecordAIRunGraphProgress
from motif_forge.application.edit_runs import CreateEditAIRun, CreateEditAIRunRequest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.piano_preview import PianoPreviewDecision, PianoPreviewRequest
from motif_forge.application.piano_study import (
    CreatePianoStudy,
    PianoStudyRequest,
    PianoStudyResult,
)
from motif_forge.application.ports import AIRunUnitOfWorkFactory, UnitOfWorkFactory
from motif_forge.domain.accompaniment import AccompanimentIntent
from motif_forge.domain.ai_runs import EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.ir import PerformancePlan, PianoRenderProfile
from motif_forge.domain.piano_requests import (
    PianoSemanticInput,
    PianoSemanticRequest,
    PianoSemanticRequestV2,
    read_piano_request,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PianoCapabilityResponse(ApiModel):
    data: PianoCapability


class PianoStudyResponse(ApiModel):
    data: PianoStudyResult


class PianoPreviewOptions(ApiModel):
    branch_id: UUID
    base_revision_id: UUID
    render_profile: PianoRenderProfile = Field(default_factory=PianoRenderProfile)
    performance_plan: PerformancePlan = Field(default_factory=PerformancePlan)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    accompaniment: AccompanimentIntent | None = None
    semantic: PianoSemanticInput | None = None

    @field_validator("semantic", mode="before")
    @classmethod
    def read_semantic(cls, value: Any) -> PianoSemanticInput | None:
        if value is None or isinstance(value, (PianoSemanticRequest, PianoSemanticRequestV2)):
            return value
        return read_piano_request(json.dumps(value))

    @field_validator("accompaniment", mode="before")
    @classmethod
    def read_accompaniment(cls, value: Any) -> AccompanimentIntent | None:
        if value is None or isinstance(value, AccompanimentIntent):
            return value
        return AccompanimentIntent.model_validate_json(json.dumps(value), strict=True)

    @field_validator("performance_plan", mode="before")
    @classmethod
    def read_performance(cls, value: Any) -> PerformancePlan:
        if isinstance(value, PerformancePlan):
            return value
        return PerformancePlan.model_validate_json(json.dumps(value), strict=True)


class PianoPreviewData(ApiModel):
    thread_id: str
    phase: str
    base_revision_id: UUID | None = None
    candidate_content_hash: str | None = None
    baseline_artifact_id: UUID | None = None
    piano_artifact_id: UUID | None = None
    revision_id: UUID | None = None
    pending_job_id: UUID | None = None
    error_code: str | None = None
    replayed: bool = False
    run_id: UUID | None = None
    semantic_summary: str | None = None
    model: str | None = None
    model_requests: int | None = None
    total_tokens: int | None = None
    usage_status: str | None = None


class PianoPreviewResponse(ApiModel):
    data: PianoPreviewData


def _response(
    values: Mapping[str, Any], thread_id: str, *, replayed: bool = False
) -> PianoPreviewResponse:
    phase = values["phase"]
    if values.get("request_payload", {}).get("semantic") and phase not in {
        "waiting_piano_worker",
        "waiting_piano_approval",
        "failed",
        "cancelled",
        "rejected",
        "completed",
    }:
        phase = "planning"
    return PianoPreviewResponse(
        data=PianoPreviewData(
            thread_id=thread_id,
            phase=phase,
            base_revision_id=values.get("request_payload", {}).get("base_revision_id"),
            candidate_content_hash=values.get("piano_data", {}).get("candidate_content_hash"),
            baseline_artifact_id=values.get("piano_baseline_artifact_id"),
            piano_artifact_id=values.get("piano_artifact_id"),
            revision_id=values.get("piano_revision_id"),
            pending_job_id=values.get("pending_job_id"),
            error_code=values.get("error_code"),
            replayed=replayed,
            run_id=values.get("run_id"),
            **{
                key: values.get("piano_data", {}).get(key)
                for key in (
                    "semantic_summary",
                    "model",
                    "model_requests",
                    "total_tokens",
                    "usage_status",
                )
            },
        )
    )


def build_piano_router(
    projects: UnitOfWorkFactory | None,
    *,
    capability: Callable[[], Awaitable[PianoCapability]],
    graph_getter: Callable[[], Any],
    ai_runs: AIRunUnitOfWorkFactory | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["piano"])

    async def respond(
        values: Mapping[str, Any], thread_id: str, *, replayed: bool = False
    ) -> PianoPreviewResponse:
        response = _response(values, thread_id, replayed=replayed)
        if ai_runs is not None and response.data.run_id is not None:
            run = await ReadAIRun(ai_runs)(response.data.run_id)
            response.data.model_requests = run.submitted_model_requests
            response.data.total_tokens = run.total_tokens
            response.data.usage_status = run.model_usage_status.value
        return response

    @router.get("/piano-capability", response_model=PianoCapabilityResponse)
    async def read_capability() -> PianoCapabilityResponse:
        return PianoCapabilityResponse(data=await capability())

    @router.post("/piano-studies", response_model=PianoStudyResponse, status_code=201)
    async def create_study(
        body: PianoStudyRequest,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
        ],
    ) -> PianoStudyResponse:
        if projects is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED", "Study creation requires persistence."
            )
        return PianoStudyResponse(
            data=await CreatePianoStudy(projects)(body, idempotency_key=idempotency_key)
        )

    def configured() -> Any:
        graph = graph_getter()
        if graph is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED", "Piano auditions require persistent checkpoints."
            )
        return graph

    @router.post(
        "/projects/{project_id}/piano-previews",
        response_model=PianoPreviewResponse,
        status_code=202,
    )
    async def start(
        project_id: UUID,
        body: PianoPreviewOptions,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
        ],
    ) -> PianoPreviewResponse:
        graph = configured()
        identity = f"{project_id}:{idempotency_key}"
        thread = "piano-" + sha256(identity.encode()).hexdigest()[:32]
        request = PianoPreviewRequest.model_validate_json(
            json.dumps(
                {
                    **body.model_dump(mode="json"),
                    "project_id": str(project_id),
                    "request_id": str(uuid5(NAMESPACE_URL, identity)),
                }
            ),
            strict=True,
        )
        if request.semantic is not None:
            if ai_runs is None:
                raise ApplicationError(
                    "PIANO_SEMANTIC_UNAVAILABLE", "Semantic planning requires the AI Run ledger."
                )
            cap = await capability()
            if not cap.available or cap.render_profile != body.render_profile:
                raise ApplicationError(
                    cap.error_code or "INSTRUMENT_PACK_UNAVAILABLE",
                    "Reviewed piano is unavailable.",
                )
            semantic = request.semantic
            selection = Selection()
            if semantic.mode == "modify":
                assert semantic.target_track_id is not None
                selection = Selection(
                    track_ids=(semantic.target_track_id,),
                    start_tick=(semantic.start_bar - 1) * semantic.bar_ticks,
                    end_tick=semantic.end_bar * semantic.bar_ticks,
                )
            run = await CreateEditAIRun(ai_runs)(
                CreateEditAIRunRequest(
                    project_id=project_id,
                    branch_id=body.branch_id,
                    base_revision_id=body.base_revision_id,
                    thread_id=thread,
                    edit_request=EditRunRequest(
                        intent=semantic.intent,
                        selection=selection,
                        piano_request=semantic,
                        seed=body.seed,
                    ),
                    idempotency_key="piano-semantic:" + sha256(identity.encode()).hexdigest(),
                    max_model_requests=1,
                    max_total_tokens=12000,
                )
            )
            snapshot = await graph.aget_state({"configurable": {"thread_id": thread}})
            if snapshot.values:
                return await respond(snapshot.values, thread, replayed=True)
            return PianoPreviewResponse(
                data=PianoPreviewData(
                    thread_id=thread,
                    phase=run.status.value,
                    base_revision_id=body.base_revision_id,
                    run_id=run.run_id,
                )
            )
        initial = initial_piano_preview_state(thread_id=thread, request=request)
        config = {"configurable": {"thread_id": thread}}
        snapshot = await graph.aget_state(config)
        replayed = bool(snapshot.values)
        if replayed:
            if any(
                snapshot.values.get(key) != dict(initial)[key]
                for key in ("operation", "project_id", "request_payload")
            ):
                raise ApplicationError(
                    "IDEMPOTENCY_KEY_REUSED", "The key was used with another piano request."
                )
            values = snapshot.values
            if (
                snapshot.next
                and not values.get("terminal_status")
                and not any(t.interrupts for t in snapshot.tasks)
            ):
                values = await graph.ainvoke(None, config)
        else:
            values = await graph.ainvoke(initial, config)
        if values.get("phase") == "failed" and not values.get("piano_data"):
            raise ApplicationError(
                values.get("error_code", "PIANO_REQUEST_INVALID"),
                "Piano audition could not be prepared.",
            )
        return await respond(values, thread, replayed=replayed)

    async def scoped(project_id: UUID, thread_id: str) -> tuple[Any, Any, dict[str, Any]]:
        if not thread_id.startswith("piano-") or len(thread_id) != 38:
            raise ApplicationError("PIANO_PREVIEW_NOT_FOUND", "Piano audition not found.")
        graph = configured()
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        if not snapshot.values and ai_runs is not None:
            run = await ReadAIRunByThreadId(ai_runs)(thread_id)
            if (
                run.project_id == project_id
                and run.edit_request
                and run.edit_request.get("piano_request")
            ):
                snapshot = SimpleNamespace(
                    values={
                        "operation": "piano_preview",
                        "project_id": str(project_id),
                        "run_id": str(run.run_id),
                        "phase": run.status.value,
                        "request_payload": {"base_revision_id": str(run.base_revision_id)},
                    },
                    next=(),
                    tasks=(),
                )
        if snapshot.values.get("operation") != "piano_preview" or snapshot.values.get(
            "project_id"
        ) != str(project_id):
            raise ApplicationError(
                "PIANO_PREVIEW_NOT_FOUND", "Piano audition does not belong to the project."
            )
        return graph, snapshot, config

    @router.get(
        "/projects/{project_id}/piano-previews/{thread_id}", response_model=PianoPreviewResponse
    )
    async def read(project_id: UUID, thread_id: str) -> PianoPreviewResponse:
        _, snapshot, _ = await scoped(project_id, thread_id)
        return await respond(snapshot.values, thread_id)

    @router.post(
        "/projects/{project_id}/piano-previews/{thread_id}/decision",
        response_model=PianoPreviewResponse,
    )
    async def decide(
        project_id: UUID, thread_id: str, body: PianoPreviewDecision
    ) -> PianoPreviewResponse:
        graph, snapshot, config = await scoped(project_id, thread_id)
        decision = body.model_dump(mode="json")
        values = snapshot.values
        if values.get("terminal_status"):
            if values.get("piano_decision") != decision:
                raise ApplicationError(
                    "PIANO_PREVIEW_STATE_CONFLICT",
                    "The audition already has a different final decision.",
                )
            return await respond(values, thread_id, replayed=True)
        if values.get("phase") != "waiting_piano_approval":
            raise ApplicationError(
                "PIANO_PREVIEW_STATE_CONFLICT", "Both auditions must finish before approval."
            )
        if body.expected_candidate_content_hash != values.get("piano_data", {}).get(
            "candidate_content_hash"
        ):
            raise ApplicationError(
                "PIANO_CANDIDATE_HASH_MISMATCH", "Approval must bind the exact candidate."
            )
        result = await graph.ainvoke(Command(resume=decision), config)
        if ai_runs is not None and result.get("run_id"):
            await RecordAIRunGraphProgress(ai_runs)(result)
        return await respond(result, thread_id)

    @router.post(
        "/projects/{project_id}/piano-previews/{thread_id}/cancel",
        response_model=PianoPreviewResponse,
    )
    async def cancel(project_id: UUID, thread_id: str) -> PianoPreviewResponse:
        graph, snapshot, config = await scoped(project_id, thread_id)
        values = snapshot.values
        if values.get("terminal_status"):
            return await respond(values, thread_id, replayed=True)
        if values.get("phase") == "waiting_piano_worker":
            resumed = {"action": "cancel"}
        elif values.get("phase") == "waiting_piano_approval":
            resumed = {
                "action": "reject",
                "expected_candidate_content_hash": values["piano_data"]["candidate_content_hash"],
                "approval_assertion": "The user rejected this piano audition.",
            }
        else:
            raise ApplicationError(
                "PIANO_PREVIEW_STATE_CONFLICT", "Piano audition is not at a cancellable boundary."
            )
        result = await graph.ainvoke(Command(resume=resumed), config)
        if ai_runs is not None and result.get("run_id"):
            await RecordAIRunGraphProgress(ai_runs)(result)
        return await respond(result, thread_id)

    return router
