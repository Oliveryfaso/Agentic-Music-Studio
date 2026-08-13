"""Transactional use cases for durable, finite AI generation runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.agent.schemas import CompositionBrief
from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, IdempotencyKeyReusedError
from motif_forge.application.ports import AIRunUnitOfWorkFactory
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunApproval,
    AIRunEvent,
    AIRunStatus,
    ModelRequestKind,
    ModelRequestReservation,
    PersistedCompositionPlan,
    approval_assertion_hash,
    composition_plan_content_hash,
)
from motif_forge.domain.ir import DomainModel

CREATE_AI_RUN_OPERATION = "ai-run.create.v1"


class ModelRequestBudgetError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__("MODEL_REQUEST_BUDGET_EXHAUSTED", message, retryable=False)


class ModelUsageFactError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__("MODEL_USAGE_INVALID", message, retryable=False)


def model_request_allowed(
    *,
    submitted_model_requests: int,
    prior_request_kinds: tuple[ModelRequestKind, ...],
    requested_kind: ModelRequestKind,
    run_status: AIRunStatus | None = None,
) -> None:
    if run_status in {
        AIRunStatus.SUCCEEDED,
        AIRunStatus.REJECTED,
        AIRunStatus.FAILED,
        AIRunStatus.CANCELLED,
    }:
        raise ModelRequestBudgetError("terminal AI runs cannot reserve model requests")
    if submitted_model_requests >= 3:
        raise ModelRequestBudgetError(
            "the run has already reserved its three upstream model requests"
        )
    repairs = {ModelRequestKind.SCHEMA_REPAIR, ModelRequestKind.STRATEGY_REPAIR}
    if requested_kind in repairs and any(kind in repairs for kind in prior_request_kinds):
        raise ModelRequestBudgetError("schema and strategy repair share one request allowance")


def validate_model_usage_facts(*, prompt_tokens: int, completion_tokens: int) -> None:
    if prompt_tokens < 0 or completion_tokens < 0:
        raise ModelUsageFactError("provider token counts must be nonnegative")


class CreateAIRunRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    brief: CompositionBrief
    idempotency_key: str = Field(min_length=8, max_length=160)
    graph_topology_version: str = Field(default="motif-forge-graph.v1", min_length=1, max_length=80)
    state_schema_version: str = Field(default="generate-run-state.v1", min_length=1, max_length=80)


class CreateAIRun:
    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._id_factory, self._clock = uow_factory, id_factory, clock

    async def __call__(self, request: CreateAIRunRequest) -> AIRun:
        fingerprint = request_hash(
            {
                "schema": CREATE_AI_RUN_OPERATION,
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        try:
            async with self._uow_factory() as transaction:
                hit = await transaction.get_ai_run_idempotency(
                    project_id=request.project_id, key=request.idempotency_key
                )
                if hit is not None:
                    if hit.request_hash != fingerprint:
                        raise IdempotencyKeyReusedError
                    return await transaction.read_ai_run(hit.resource_id)
                now = self._clock()
                run = AIRun(
                    run_id=self._id_factory(),
                    project_id=request.project_id,
                    branch_id=request.branch_id,
                    base_revision_id=request.base_revision_id,
                    thread_id=request.thread_id,
                    brief=request.brief.model_dump(mode="json"),
                    idempotency_key=request.idempotency_key,
                    graph_topology_version=request.graph_topology_version,
                    state_schema_version=request.state_schema_version,
                    created_at=now,
                    updated_at=now,
                )
                await transaction.create_ai_run(
                    run=run,
                    created_event=AIRunEvent(
                        sequence=1,
                        event_id=self._id_factory(),
                        run_id=run.run_id,
                        event_type="ai_run.created",
                        phase="queued",
                        payload={"thread_id": run.thread_id},
                        dedupe_key="created",
                        created_at=now,
                    ),
                    outbox_event_id=self._id_factory(),
                    request_hash=fingerprint,
                )
                return run
        except ApplicationError as exc:
            if exc.code != "AI_RUN_CREATE_RACE":
                raise
        async with self._uow_factory() as transaction:
            hit = await transaction.get_ai_run_idempotency(
                project_id=request.project_id, key=request.idempotency_key
            )
            if hit is None or hit.request_hash != fingerprint:
                raise IdempotencyKeyReusedError
            return await transaction.read_ai_run(hit.resource_id)


class PersistCompositionPlan:
    def __init__(self, uow_factory: AIRunUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, persisted: PersistedCompositionPlan) -> PersistedCompositionPlan:
        if persisted.content_hash != composition_plan_content_hash(persisted.plan):
            raise ApplicationError("PLAN_HASH_MISMATCH", "the CompositionPlan hash is invalid")
        async with self._uow_factory() as transaction:
            return await transaction.persist_composition_plan(persisted)


class RecordAIRunEvent:
    def __init__(self, uow_factory: AIRunUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, event: AIRunEvent) -> AIRunEvent:
        async with self._uow_factory() as transaction:
            return await transaction.record_ai_run_event(event)


class ReadAIRun:
    def __init__(self, uow_factory: AIRunUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, run_id: UUID) -> AIRun:
        async with self._uow_factory() as transaction:
            return await transaction.read_ai_run(run_id)


class ListAIRunEvents:
    def __init__(self, uow_factory: AIRunUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, run_id: UUID, *, after_sequence: int = 0) -> tuple[AIRunEvent, ...]:
        async with self._uow_factory() as transaction:
            return await transaction.list_ai_run_events(run_id, after_sequence=after_sequence)


class RequestAIRunAction:
    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._id_factory, self._clock = uow_factory, id_factory, clock

    async def __call__(
        self, *, run_id: UUID, action: str, expected_version: int, idempotency_key: str
    ) -> AIRun:
        if action not in {"resume", "cancel", "retry"}:
            raise ApplicationError("AI_RUN_ACTION_INVALID", "unsupported AI run action")
        async with self._uow_factory() as transaction:
            return await transaction.request_ai_run_action(
                run_id=run_id,
                action=action,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                outbox_event_id=self._id_factory(),
                now=self._clock(),
            )


class RecordAIRunApproval:
    """Atomically persist the hashed human assertion and the approval decision."""

    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._id_factory, self._clock = uow_factory, id_factory, clock

    async def __call__(
        self,
        *,
        run_id: UUID,
        actor_id: str,
        decision: str,
        assertion: str,
        expected_version: int,
    ) -> AIRunApproval:
        if decision not in {"approve", "reject"}:
            raise ApplicationError(
                "AI_RUN_APPROVAL_INVALID", "approval decision must be approve or reject"
            )
        now = self._clock()
        approval = AIRunApproval(
            approval_id=self._id_factory(),
            run_id=run_id,
            assertion_hash=approval_assertion_hash(assertion),
            decision=decision,
            actor_id=actor_id,
            decided_at=now,
        )
        async with self._uow_factory() as transaction:
            return await transaction.record_ai_run_approval(
                approval=approval,
                expected_version=expected_version,
                outbox_event_id=self._id_factory(),
            )


class ReserveModelRequest:
    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._id_factory, self._clock = uow_factory, id_factory, clock

    async def __call__(self, *, run_id: UUID, kind: ModelRequestKind) -> ModelRequestReservation:
        async with self._uow_factory() as transaction:
            return await transaction.reserve_model_request(
                run_id=run_id, kind=kind, reservation_id=self._id_factory(), now=self._clock()
            )


class RecordModelUsage:
    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._clock = uow_factory, clock

    async def __call__(
        self,
        *,
        run_id: UUID,
        reservation_id: UUID,
        provider_operation_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> ModelRequestReservation:
        validate_model_usage_facts(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        async with self._uow_factory() as transaction:
            return await transaction.record_model_usage(
                run_id=run_id,
                reservation_id=reservation_id,
                provider_operation_id=provider_operation_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                now=self._clock(),
            )
