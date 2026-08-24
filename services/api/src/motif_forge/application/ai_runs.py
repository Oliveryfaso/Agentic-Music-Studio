"""Transactional use cases for durable, finite AI generation runs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.agent.schemas import CompositionBrief, PlanAdjustment
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
from motif_forge.domain.candidates import CandidateCritique
from motif_forge.domain.ir import DomainModel

CREATE_AI_RUN_OPERATION = "ai-run.create.v1"
REPLAN_AI_RUN_OPERATION = "ai-run.replan.v1"


def _adjustment_preferences(adjustment: PlanAdjustment) -> tuple[str, ...]:
    parts: list[str] = []
    if adjustment.sections is not None:
        parts.extend(
            f"S:{section.name},bars={section.bars},energy={section.energy:g}"
            for section in adjustment.sections
        )
    if adjustment.instrumentation is not None:
        parts.extend(
            f"I:{instrument.name},role={instrument.role}"
            for instrument in adjustment.instrumentation
        )
    if adjustment.note:
        parts.append(f"N:{adjustment.note}")
    normalized = " | ".join(parts)
    return tuple(normalized[index : index + 240] for index in range(0, len(normalized), 240))


def derive_replan_brief(
    parent: CompositionBrief, adjustment: PlanAdjustment
) -> CompositionBrief:
    """Project reviewed intent into the one existing strict planning input."""

    normalized = _adjustment_preferences(adjustment)
    if len(normalized) > 16:
        raise ApplicationError(
            "PLAN_ADJUSTMENT_TOO_LARGE",
            "the normalized Plan adjustment exceeds the Brief preference boundary",
        )
    preserved = parent.soft_preferences[: 16 - len(normalized)]
    return parent.model_copy(
        update={
            "target_bpm": (
                adjustment.target_bpm
                if adjustment.target_bpm is not None
                else parent.target_bpm
            ),
            "target_key": (
                adjustment.target_key
                if adjustment.target_key is not None
                else parent.target_key
            ),
            "preferred_instruments": (
                tuple(item.name for item in adjustment.instrumentation)
                if adjustment.instrumentation is not None
                else parent.preferred_instruments
            ),
            "soft_preferences": (*normalized, *preserved),
        }
    )


class ReplanAIRunRequest(DomainModel):
    run_id: UUID
    expected_version: int = Field(ge=0)
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjustment: PlanAdjustment
    idempotency_key: str = Field(min_length=8, max_length=160)


class ReplanAIRun:
    """Create one immutable child Run without calling the planner synchronously."""

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

    async def __call__(self, request: ReplanAIRunRequest) -> AIRun:
        async with self._uow_factory() as transaction:
            parent = await transaction.read_ai_run(request.run_id)
        if parent.brief is None:
            raise ApplicationError("AI_RUN_BRIEF_INVALID", "the parent Run has no planning Brief")
        try:
            parent_brief = CompositionBrief.model_validate_json(
                json.dumps(parent.brief), strict=True
            )
        except ValueError:
            raise ApplicationError(
                "AI_RUN_BRIEF_INVALID", "the parent Run planning Brief is invalid"
            ) from None
        child_brief = derive_replan_brief(parent_brief, request.adjustment)
        fingerprint = request_hash(
            {
                "schema": REPLAN_AI_RUN_OPERATION,
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
                "child_brief": child_brief.model_dump(mode="json"),
            }
        )
        async with self._uow_factory() as transaction:
            return await transaction.replan_ai_run(
                parent_run_id=request.run_id,
                expected_version=request.expected_version,
                expected_plan_hash=request.expected_plan_hash,
                idempotency_key=request.idempotency_key,
                child_run_id=self._id_factory(),
                child_thread_id=f"replan-{self._id_factory()}",
                child_brief=child_brief.model_dump(mode="json"),
                created_event_id=self._id_factory(),
                outbox_event_id=self._id_factory(),
                request_hash=fingerprint,
                now=self._clock(),
            )


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
    if terminal == "rejected":
        return run_id, AIRunStatus.REJECTED, None
    if terminal == "cancelled":
        return run_id, AIRunStatus.CANCELLED, None
    if state.get("phase") in {"waiting_generate_worker", "waiting_worker"}:
        return run_id, AIRunStatus.WAITING_WORKER, None
    if state.get("phase") == "waiting_edit_approval":
        return run_id, AIRunStatus.WAITING_EDIT_APPROVAL, None
    if state.get("phase") == "committed":
        return run_id, AIRunStatus.SUCCEEDED, None
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


class ReadAIRunByThreadId:
    def __init__(self, uow_factory: AIRunUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, thread_id: str) -> AIRun:
        async with self._uow_factory() as transaction:
            return await transaction.read_ai_run_by_thread_id(thread_id)


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


class ResumeAIRunCandidateSelection:
    """Persistently idempotent CandidateSelection wake for the existing Parent Graph."""

    def __init__(
        self, uow_factory: AIRunUnitOfWorkFactory, *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._id_factory, self._clock = uow_factory, id_factory, clock

    async def __call__(
        self, *, run_id: UUID, actor_id: str, decision: str, assertion: str,
        selected_preview_id: UUID | None, expected_candidate_id: UUID | None,
        expected_candidate_content_hash: str | None, expected_version: int,
        note: str, idempotency_key: str,
    ) -> AIRun:
        fingerprint = request_hash({
            "run_id": str(run_id), "actor_id": actor_id, "decision": decision,
            "assertion": assertion, "selected_preview_id": selected_preview_id,
            "expected_candidate_id": expected_candidate_id,
            "expected_candidate_content_hash": expected_candidate_content_hash,
            "expected_version": expected_version, "note": note,
        })
        async with self._uow_factory() as transaction:
            hit = await transaction.get_ai_run_action_idempotency(
                parent_run_id=run_id, action="select_candidate", key=idempotency_key
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return await transaction.read_ai_run(hit.resource_id)
            projection = await transaction.read_ai_run_projection(run_id)
            if projection.revision_id is not None or len(projection.candidates) != 2:
                raise ApplicationError(
                    "AI_RUN_ACTION_STATE_CONFLICT", "run is not awaiting candidate selection"
                )
            if decision == "select":
                selected = next(
                    (
                        item for item in projection.candidates
                        if item.preview_id == selected_preview_id
                    ),
                    None,
                )
                if (
                    selected is None
                    or selected.candidate_id != expected_candidate_id
                    or selected.candidate_content_hash != expected_candidate_content_hash
                ):
                    raise ApplicationError(
                        "CANDIDATE_SELECTION_MISMATCH",
                        "selection must bind one authoritative candidate Preview",
                    )
            elif any(item is not None for item in (
                selected_preview_id, expected_candidate_id, expected_candidate_content_hash
            )):
                raise ApplicationError(
                    "CANDIDATE_SELECTION_INVALID", "candidate rejection forbids Preview identity"
                )
            await transaction.record_idempotent_candidate_selection(
                run_id=run_id, actor_id=actor_id, decision=decision, assertion=assertion,
                selected_preview_id=selected_preview_id,
                expected_candidate_id=expected_candidate_id,
                expected_candidate_content_hash=expected_candidate_content_hash,
                note=note, expected_version=expected_version,
                idempotency_key=idempotency_key, request_hash=fingerprint,
                outbox_event_id=self._id_factory(), event_id=self._id_factory(),
                now=self._clock(),
            )
            return await transaction.read_ai_run(run_id)


class RecordCandidateCritique:
    """Persist the strict Critic result as a replayable Run event."""

    def __init__(
        self, uow_factory: AIRunUnitOfWorkFactory, *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory, self._id_factory, self._clock = uow_factory, id_factory, clock

    async def __call__(self, run_id: UUID, critique: CandidateCritique) -> None:
        async with self._uow_factory() as transaction:
            await transaction.record_ai_run_event(AIRunEvent(
                sequence=1, event_id=self._id_factory(), run_id=run_id,
                event_type="candidate.critic.completed", phase="criticizing",
                payload=critique.model_dump(mode="json"),
                dedupe_key="candidate-critic:v1", created_at=self._clock(),
            ))


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
