"""Transactional use cases for durable, finite AI generation runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.agent.schemas import CompositionBrief
from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, IdempotencyKeyReusedError
from motif_forge.application.ports import AIRunProjection, AIRunUnitOfWorkFactory
from motif_forge.domain.ai_runs import (
    GENERATE_RUN_STATE_SCHEMA_VERSION,
    PARENT_GRAPH_TOPOLOGY_VERSION,
    AIRun,
    AIRunApproval,
    AIRunEvent,
    AIRunStatus,
    ModelRequestKind,
    ModelRequestReservation,
    ModelUsageStatus,
    PersistedCompositionPlan,
    approval_assertion_hash,
    composition_plan_content_hash,
)
from motif_forge.domain.ir import DomainModel

CREATE_AI_RUN_OPERATION = "ai-run.create.v1"


def graph_progress_target(
    state: Mapping[str, object],
) -> tuple[UUID, AIRunStatus, str | None] | None:
    """Map a validated Parent Graph result to the authoritative AI Run ledger."""

    raw_run_id = state.get("run_id")
    if not isinstance(raw_run_id, str):
        return None
    try:
        run_id = UUID(raw_run_id)
    except ValueError:
        return None
    terminal = state.get("terminal_status")
    if terminal == "succeeded":
        return run_id, AIRunStatus.SUCCEEDED, None
    if terminal == "failed":
        error_code = state.get("error_code")
        return (
            run_id,
            AIRunStatus.FAILED,
            error_code if isinstance(error_code, str) else "GRAPH_TERMINAL_FAILURE",
        )
    if state.get("phase") == "waiting_generate_worker":
        return run_id, AIRunStatus.WAITING_WORKER, None
    return None


class RecordAIRunGraphProgress:
    """Idempotently project Graph worker/terminal progress into the AI Run ledger."""

    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, state: Mapping[str, object]) -> None:
        target = graph_progress_target(state)
        if target is None:
            return
        run_id, status, error_code = target
        async with self._uow_factory() as transaction:
            await transaction.record_ai_run_graph_progress(
                run_id=run_id,
                target_status=status,
                error_code=error_code,
                event_id=self._id_factory(),
                now=self._clock(),
            )


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
    max_model_requests: int = 3,
    run_status: AIRunStatus | None = None,
) -> None:
    if run_status in {
        AIRunStatus.SUCCEEDED,
        AIRunStatus.REJECTED,
        AIRunStatus.FAILED,
        AIRunStatus.CANCELLED,
    }:
        raise ModelRequestBudgetError("terminal AI runs cannot reserve model requests")
    if not 1 <= max_model_requests <= 3:
        raise ModelRequestBudgetError("the persisted model request ceiling is invalid")
    if submitted_model_requests >= max_model_requests:
        raise ModelRequestBudgetError(
            "the run has already reserved its locked upstream model request budget"
        )
    repairs = {ModelRequestKind.SCHEMA_REPAIR, ModelRequestKind.STRATEGY_REPAIR}
    if requested_kind in repairs and any(kind in repairs for kind in prior_request_kinds):
        raise ModelRequestBudgetError("schema and strategy repair share one request allowance")


def validate_model_usage_facts(
    *,
    usage_status: ModelUsageStatus,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    prompt_cache_hit_tokens: int | None,
    prompt_cache_miss_tokens: int | None,
    reasoning_tokens: int | None,
) -> None:
    facts = (
        prompt_tokens,
        completion_tokens,
        total_tokens,
        prompt_cache_hit_tokens,
        prompt_cache_miss_tokens,
        reasoning_tokens,
    )
    if any(value is not None and value < 0 for value in facts):
        raise ModelUsageFactError("provider token counts must be nonnegative")
    if usage_status is ModelUsageStatus.UNKNOWN and any(value is not None for value in facts):
        raise ModelUsageFactError("unknown usage cannot carry provider token facts")
    if usage_status is not ModelUsageStatus.UNKNOWN and all(value is None for value in facts):
        raise ModelUsageFactError("known or partial usage requires a provider token fact")
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        raise ModelUsageFactError("derivable total tokens must be recorded explicitly")


class CreateAIRunRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    brief: CompositionBrief
    idempotency_key: str = Field(min_length=8, max_length=160)
    max_model_requests: int = Field(default=3, ge=1, le=3)
    max_total_tokens: int = Field(default=12_000, ge=1, le=12_000)
    graph_topology_version: str = Field(
        default=PARENT_GRAPH_TOPOLOGY_VERSION, min_length=1, max_length=80
    )
    state_schema_version: str = Field(
        default=GENERATE_RUN_STATE_SCHEMA_VERSION, min_length=1, max_length=80
    )


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
                    max_model_requests=request.max_model_requests,
                    max_total_tokens=request.max_total_tokens,
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
        if persisted.content_hash != composition_plan_content_hash(
            persisted.plan, hash_version=persisted.hash_version
        ):
            raise ApplicationError("PLAN_HASH_MISMATCH", "the CompositionPlan hash is invalid")
        async with self._uow_factory() as transaction:
            return await transaction.persist_composition_plan(persisted)


class MarkAIRunPlanPending:
    """Create the durable, server-authoritative approval interrupt for one Plan."""

    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._clock = uow_factory, clock

    async def __call__(self, *, run_id: UUID, plan_id: UUID, expected_version: int) -> AIRun:
        async with self._uow_factory() as transaction:
            return await transaction.mark_ai_run_plan_pending(
                run_id=run_id, plan_id=plan_id, expected_version=expected_version, now=self._clock()
            )


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


class ReadAIRunProjection:
    def __init__(self, uow_factory: AIRunUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, run_id: UUID) -> AIRunProjection:
        async with self._uow_factory() as transaction:
            return await transaction.read_ai_run_projection(run_id)


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
        if action not in {"cancel", "retry"}:
            raise ApplicationError("AI_RUN_ACTION_INVALID", "unsupported AI run action")
        async with self._uow_factory() as transaction:
            if action == "retry":
                action_hash = request_hash(
                    {
                        "parent_run_id": str(run_id),
                        "action": action,
                        "expected_version": expected_version,
                    }
                )
                return await transaction.retry_ai_run(
                    parent_run_id=run_id,
                    expected_version=expected_version,
                    idempotency_key=idempotency_key,
                    child_run_id=self._id_factory(),
                    child_thread_id=f"retry-{self._id_factory()}",
                    created_event_id=self._id_factory(),
                    outbox_event_id=self._id_factory(),
                    request_hash=action_hash,
                    now=self._clock(),
                )
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
        expected_plan_content_hash: str,
        interrupt_ref: str,
        note: str = "",
        idempotency_key: str | None = None,
    ) -> AIRunApproval:
        if decision not in {"approve", "reject"}:
            raise ApplicationError(
                "AI_RUN_APPROVAL_INVALID", "approval decision must be approve or reject"
            )
        if not 16 <= len(assertion) <= 500:
            raise ApplicationError(
                "AI_RUN_APPROVAL_INVALID",
                "approval assertion must be between 16 and 500 characters",
            )
        now = self._clock()
        approval = AIRunApproval(
            approval_id=self._id_factory(),
            run_id=run_id,
            assertion_hash=approval_assertion_hash(assertion),
            decision=decision,
            actor_id=actor_id,
            expected_plan_content_hash=expected_plan_content_hash,
            interrupt_ref=interrupt_ref,
            decided_at=now,
        )
        async with self._uow_factory() as transaction:
            if idempotency_key is not None:
                fingerprint = request_hash({
                    "run_id": str(run_id), "actor_id": actor_id, "decision": decision,
                    "assertion": assertion,
                    "expected_plan_content_hash": expected_plan_content_hash,
                    "interrupt_ref": interrupt_ref, "note": note,
                })
                return await transaction.record_idempotent_ai_run_approval(
                    approval=approval, assertion=assertion, note=note,
                    expected_version=expected_version, idempotency_key=idempotency_key,
                    request_hash=fingerprint, outbox_event_id=self._id_factory(),
                )
            return await transaction.record_ai_run_approval(
                approval=approval,
                assertion=assertion,
                note=note,
                expected_version=expected_version,
                outbox_event_id=self._id_factory(),
            )


class ResumeAIRunApproval:
    """Idempotent public approval: replay lookup precedes live pending-state validation."""

    def __init__(
        self, uow_factory: AIRunUnitOfWorkFactory, *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._id_factory, self._clock = uow_factory, id_factory, clock

    async def __call__(
        self, *, run_id: UUID, actor_id: str, decision: str, assertion: str,
        expected_version: int, expected_plan_content_hash: str, note: str,
        idempotency_key: str,
    ) -> AIRun:
        fingerprint = request_hash({
            "run_id": str(run_id), "actor_id": actor_id, "decision": decision,
            "assertion": assertion, "expected_version": expected_version,
            "expected_plan_content_hash": expected_plan_content_hash, "note": note,
        })
        async with self._uow_factory() as transaction:
            hit = await transaction.get_ai_run_action_idempotency(
                parent_run_id=run_id, action="resume", key=idempotency_key
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return await transaction.read_ai_run(hit.resource_id)
            run = await transaction.read_ai_run(run_id)
            if run.pending_plan_content_hash != expected_plan_content_hash:
                raise ApplicationError("PLAN_HASH_MISMATCH", "approval must bind the pending Plan")
            if run.pending_interrupt_ref is None:
                raise ApplicationError(
                    "AI_RUN_ACTION_STATE_CONFLICT", "run is not awaiting approval"
                )
            approval = AIRunApproval(
                approval_id=self._id_factory(), run_id=run_id,
                assertion_hash=approval_assertion_hash(assertion), decision=decision,
                actor_id=actor_id, expected_plan_content_hash=expected_plan_content_hash,
                interrupt_ref=run.pending_interrupt_ref, decided_at=self._clock(),
            )
            await transaction.record_idempotent_ai_run_approval(
                approval=approval, assertion=assertion, note=note,
                expected_version=expected_version, idempotency_key=idempotency_key,
                request_hash=fingerprint, outbox_event_id=self._id_factory(),
            )
            return await transaction.read_ai_run(run_id)


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
        usage_status: ModelUsageStatus,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        prompt_cache_hit_tokens: int | None,
        prompt_cache_miss_tokens: int | None,
        reasoning_tokens: int | None,
    ) -> ModelRequestReservation:
        validate_model_usage_facts(
            usage_status=usage_status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            prompt_cache_hit_tokens=prompt_cache_hit_tokens,
            prompt_cache_miss_tokens=prompt_cache_miss_tokens,
            reasoning_tokens=reasoning_tokens,
        )
        async with self._uow_factory() as transaction:
            return await transaction.record_model_usage(
                run_id=run_id,
                reservation_id=reservation_id,
                provider_operation_id=provider_operation_id,
                usage_status=usage_status,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                prompt_cache_hit_tokens=prompt_cache_hit_tokens,
                prompt_cache_miss_tokens=prompt_cache_miss_tokens,
                reasoning_tokens=reasoning_tokens,
                now=self._clock(),
            )
