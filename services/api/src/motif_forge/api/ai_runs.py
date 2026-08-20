"""Durable AI Run HTTP contracts and persistent event streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, PlanAdjustment
from motif_forge.application.ai_runs import (
    CreateAIRun,
    CreateAIRunRequest,
    ListAIRunEvents,
    ReadAIRun,
    ReadAIRunProjection,
    ReplanAIRun,
    ReplanAIRunRequest,
    RequestAIRunAction,
    ResumeAIRunApproval,
)
from motif_forge.application.ports import AIRunProgress, AIRunProjection, AIRunUnitOfWorkFactory
from motif_forge.domain.ai_runs import AIRun, AIRunEvent, AIRunStatus, PlanHashVersion

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=160)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateAIRunBody(ApiModel):
    branch_id: UUID
    base_revision_id: UUID
    max_model_requests: int = Field(default=3, ge=1, le=3)
    max_total_tokens: int = Field(default=12_000, ge=1, le=12_000)
    brief: dict[str, object]

    @field_validator("brief")
    @classmethod
    def validate_brief(cls, value: dict[str, object]) -> dict[str, object]:
        CompositionBrief.model_validate(value, strict=False)
        return value


class ResumeAIRunBody(ApiModel):
    expected_version: int = Field(ge=0)
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: str = Field(min_length=1, max_length=160)
    approval_assertion: str = Field(min_length=16, max_length=500)
    decision: Literal["approve", "reject"] = "approve"
    note: str = Field(default="", max_length=500)


class RunActionBody(ApiModel):
    expected_version: int = Field(ge=0)


class ReplanAIRunBody(ApiModel):
    expected_version: int = Field(ge=0)
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjustment: dict[str, object]

    @field_validator("adjustment")
    @classmethod
    def validate_adjustment(cls, value: dict[str, object]) -> dict[str, object]:
        PlanAdjustment.model_validate_json(json.dumps(value), strict=True)
        return value


class RunPlanData(ApiModel):
    plan_id: UUID
    content_hash: str
    hash_version: PlanHashVersion
    plan: CompositionPlan
    provider: str
    model: str
    fallback_reason: str | None


class RunProgressData(ApiModel):
    phase: AIRunStatus
    completed_export_steps: tuple[str, ...]
    total_export_steps: int = Field(ge=0)
    latest_event_sequence: int = Field(ge=0)
    error_code: str | None


class AIRunData(ApiModel):
    run_id: UUID
    parent_run_id: UUID | None
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    thread_id: str
    status: AIRunStatus
    version: int
    pending_action: Literal["approve_plan"] | None
    pending_plan_id: UUID | None
    pending_plan_hash: str | None
    submitted_model_requests: int
    max_model_requests: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    model_usage_status: str
    cost_status: str
    cost_amount_microusd: int | None
    cost_pricing_version: str | None
    revision_id: UUID | None = None
    bundle_id: UUID | None = None
    fallback_reason: str | None = None
    error_code: str | None = None
    plan: RunPlanData | None = None
    progress: RunProgressData


def run_data(run: AIRun, projection: AIRunProjection | None = None) -> AIRunData:
    progress = (
        projection.progress
        if projection and projection.progress
        else AIRunProgress(
            phase=run.status,
            completed_export_steps=(),
            total_export_steps=7,
            latest_event_sequence=0,
            error_code=projection.error_code if projection else None,
        )
    )
    return AIRunData(
        run_id=run.run_id, parent_run_id=run.parent_run_id, project_id=run.project_id,
        branch_id=run.branch_id, base_revision_id=run.base_revision_id,
        thread_id=run.thread_id, status=run.status, version=run.version,
        pending_action="approve_plan" if run.status is AIRunStatus.WAITING_APPROVAL else None,
        pending_plan_id=run.pending_plan_id, pending_plan_hash=run.pending_plan_content_hash,
        submitted_model_requests=run.submitted_model_requests,
        max_model_requests=run.max_model_requests, prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens, total_tokens=run.total_tokens,
        model_usage_status=run.model_usage_status.value, cost_status=run.cost.status.value,
        cost_amount_microusd=run.cost.amount_microusd,
        cost_pricing_version=run.cost.pricing_version,
        revision_id=projection.revision_id if projection else None,
        bundle_id=projection.bundle_id if projection else None,
        fallback_reason=projection.fallback_reason if projection else None,
        error_code=projection.error_code if projection else None,
        plan=(
            RunPlanData(
                plan_id=projection.plan.plan_id,
                content_hash=projection.plan.content_hash,
                hash_version=projection.plan.hash_version,
                plan=projection.plan.plan,
                provider=projection.plan.provider,
                model=projection.plan.model,
                fallback_reason=projection.plan.fallback_reason,
            )
            if projection and projection.plan
            else None
        ),
        progress=RunProgressData(
            phase=progress.phase,
            completed_export_steps=progress.completed_export_steps,
            total_export_steps=progress.total_export_steps,
            latest_event_sequence=progress.latest_event_sequence,
            error_code=progress.error_code,
        ),
    )


def format_sse_event(event: AIRunEvent) -> str:
    data = event.model_dump(mode="json")
    return (
        f"id: {event.sequence}\n"
        f"event: {event.event_type}\n"
        f"data: {json.dumps(data, separators=(',', ':'))}\n\n"
    )


def build_ai_run_router(uow: AIRunUnitOfWorkFactory) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["ai-runs"])

    @router.post("/projects/{project_id}/ai-runs", status_code=202)
    async def create_run(
        project_id: UUID, body: CreateAIRunBody, idempotency_key: IdempotencyKey
    ) -> dict[str, object]:
        brief = CompositionBrief.model_validate(body.brief, strict=False)
        run = await CreateAIRun(uow)(CreateAIRunRequest(
            project_id=project_id, branch_id=body.branch_id,
            base_revision_id=body.base_revision_id,
            thread_id=f"generate-{idempotency_key}", brief=brief,
            idempotency_key=idempotency_key,
            max_model_requests=body.max_model_requests,
            max_total_tokens=body.max_total_tokens,
        ))
        return {"status": "accepted", "data": run_data(run).model_dump(mode="json")}

    @router.get("/runs/{run_id}")
    async def read_run(run_id: UUID) -> dict[str, object]:
        projection = await ReadAIRunProjection(uow)(run_id)
        return {"data": run_data(projection.run, projection).model_dump(mode="json")}

    @router.post("/runs/{run_id}/resume")
    async def resume_run(
        run_id: UUID, body: ResumeAIRunBody, idempotency_key: IdempotencyKey
    ) -> dict[str, object]:
        run = await ResumeAIRunApproval(uow)(
            run_id=run_id, actor_id=body.actor_id, decision=body.decision,
            assertion=body.approval_assertion, expected_version=body.expected_version,
            expected_plan_content_hash=body.expected_plan_hash,
            note=body.note, idempotency_key=idempotency_key,
        )
        return {"data": run_data(run).model_dump(mode="json")}

    async def action(run_id: UUID, body: RunActionBody, key: str, name: str) -> dict[str, object]:
        run = await RequestAIRunAction(uow)(
            run_id=run_id, action=name, expected_version=body.expected_version,
            idempotency_key=key,
        )
        return {"data": run_data(run).model_dump(mode="json")}

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(
        run_id: UUID, body: RunActionBody, idempotency_key: IdempotencyKey
    ) -> dict[str, object]:
        return await action(run_id, body, idempotency_key, "cancel")

    @router.post("/runs/{run_id}/retry", status_code=202)
    async def retry_run(
        run_id: UUID, body: RunActionBody, idempotency_key: IdempotencyKey
    ) -> dict[str, object]:
        return await action(run_id, body, idempotency_key, "retry")

    @router.post("/runs/{run_id}/replan", status_code=202)
    async def replan_run(
        run_id: UUID, body: ReplanAIRunBody, idempotency_key: IdempotencyKey
    ) -> dict[str, object]:
        adjustment = PlanAdjustment.model_validate_json(
            json.dumps(body.adjustment), strict=True
        )
        run = await ReplanAIRun(uow)(ReplanAIRunRequest(
            run_id=run_id,
            expected_version=body.expected_version,
            expected_plan_hash=body.expected_plan_hash,
            adjustment=adjustment,
            idempotency_key=idempotency_key,
        ))
        return {"data": run_data(run).model_dump(mode="json")}

    @router.get("/runs/{run_id}/events")
    async def stream_events(
        run_id: UUID, request: Request,
        last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        async def generate() -> AsyncIterator[str]:
            after = last_event_id or 0
            while True:
                events = await ListAIRunEvents(uow)(run_id, after_sequence=after)
                if events:
                    for event in events:
                        after = event.sequence
                        yield format_sse_event(event)
                    run = await ReadAIRun(uow)(run_id)
                    if run.terminal_at is not None:
                        return
                else:
                    run = await ReadAIRun(uow)(run_id)
                    if run.terminal_at is not None:
                        return
                    yield ": heartbeat\n\n"
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return router
