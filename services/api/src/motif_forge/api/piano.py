"""Persistent manual piano audition, exact approval and explicit study entry."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Header
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, field_validator

from motif_forge.agent.parent_graph import initial_piano_preview_state
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.piano_preview import PianoPreviewDecision, PianoPreviewRequest
from motif_forge.application.piano_study import (
    CreatePianoStudy,
    PianoStudyRequest,
    PianoStudyResult,
)
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.ir import PerformancePlan, PianoRenderProfile


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


class PianoPreviewResponse(ApiModel):
    data: PianoPreviewData


def _response(
    values: Mapping[str, Any], thread_id: str, *, replayed: bool = False
) -> PianoPreviewResponse:
    return PianoPreviewResponse(
        data=PianoPreviewData(
            thread_id=thread_id,
            phase=values["phase"],
            base_revision_id=values.get("request_payload", {}).get("base_revision_id"),
            candidate_content_hash=values.get("piano_data", {}).get("candidate_content_hash"),
            baseline_artifact_id=values.get("piano_baseline_artifact_id"),
            piano_artifact_id=values.get("piano_artifact_id"),
            revision_id=values.get("piano_revision_id"),
            pending_job_id=values.get("pending_job_id"),
            error_code=values.get("error_code"),
            replayed=replayed,
        )
    )


def build_piano_router(
    projects: UnitOfWorkFactory | None,
    *,
    capability: Callable[[], Awaitable[PianoCapability]],
    graph_getter: Callable[[], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["piano"])

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
        return _response(values, thread, replayed=replayed)

    async def scoped(project_id: UUID, thread_id: str) -> tuple[Any, Any, dict[str, Any]]:
        if not thread_id.startswith("piano-") or len(thread_id) != 38:
            raise ApplicationError("PIANO_PREVIEW_NOT_FOUND", "Piano audition not found.")
        graph = configured()
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
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
        return _response(snapshot.values, thread_id)

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
            return _response(values, thread_id, replayed=True)
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
        return _response(await graph.ainvoke(Command(resume=decision), config), thread_id)

    @router.post(
        "/projects/{project_id}/piano-previews/{thread_id}/cancel",
        response_model=PianoPreviewResponse,
    )
    async def cancel(project_id: UUID, thread_id: str) -> PianoPreviewResponse:
        graph, snapshot, config = await scoped(project_id, thread_id)
        values = snapshot.values
        if values.get("terminal_status"):
            return _response(values, thread_id, replayed=True)
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
        return _response(await graph.ainvoke(Command(resume=resumed), config), thread_id)

    return router
