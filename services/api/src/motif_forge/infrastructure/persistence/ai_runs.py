"""PostgreSQL implementation of the durable S2 AI-run ledger."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motif_forge.application.ai_runs import model_request_allowed
from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import IdempotencyHit
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunApproval,
    AIRunEvent,
    AIRunStatus,
    CostStatus,
    ModelCost,
    ModelRequestKind,
    ModelRequestReservation,
    ModelRequestReservationStatus,
    PersistedCompositionPlan,
)
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import (
    AIRunApprovalRow,
    AIRunEventRow,
    AIRunRow,
    BranchRow,
    CompositionPlanRow,
    ModelRequestReservationRow,
    OutboxEventRow,
    RevisionRow,
)


class PostgresAIRunUnitOfWork:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresAIRunTransaction:
        return PostgresAIRunTransaction(self._session_factory())


class PostgresAIRunTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()

    async def get_ai_run_idempotency(self, *, project_id: UUID, key: str) -> IdempotencyHit | None:
        row = (
            await self._session.execute(
                select(AIRunRow).where(
                    AIRunRow.project_id == project_id,
                    AIRunRow.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return IdempotencyHit(
            resource_id=row.id,
            request_hash=_ai_run_request_hash(row),
            result_payload={"run_id": str(row.id), "project_id": str(row.project_id)},
        )

    async def create_ai_run(
        self, *, run: AIRun, created_event: AIRunEvent, outbox_event_id: UUID, request_hash: str
    ) -> None:
        branch = (
            await self._session.execute(
                select(BranchRow)
                .where(BranchRow.id == run.branch_id, BranchRow.project_id == run.project_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        revision = (
            await self._session.execute(
                select(RevisionRow).where(
                    RevisionRow.id == run.base_revision_id,
                    RevisionRow.project_id == run.project_id,
                )
            )
        ).scalar_one_or_none()
        if branch is None or revision is None:
            raise ApplicationError(
                "AI_RUN_IDENTITY_INVALID",
                "branch and base revision must belong to the requested project",
            )
        if branch.head_revision_id != run.base_revision_id:
            raise ApplicationError(
                "AI_RUN_BASE_REVISION_CONFLICT",
                "base revision must be the locked branch head",
            )
        try:
            await self._session.execute(insert(AIRunRow).values(**_run_values(run)))
        except IntegrityError as exc:
            # A concurrent identical request wins by reading the project-scoped natural key.
            # The outer UoW rolls back, then CreateAIRun opens a fresh UoW to replay it.
            raise ApplicationError(
                "AI_RUN_CREATE_RACE", "concurrent AI run creation must be replayed"
            ) from exc
        await self._session.execute(
            insert(AIRunEventRow).values(**_event_values(created_event, sequence=None))
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="ai_run",
                aggregate_id=run.run_id,
                topic="graph.start.requested",
                dedupe_key=f"ai-run:{run.run_id}:graph.start.requested",
                payload={
                    "schema_version": "graph-start-request.v1",
                    "run_id": str(run.run_id),
                    "thread_id": run.thread_id,
                    "run_type": "generate",
                },
                status="pending",
                attempts=0,
                available_at=run.created_at,
                created_at=run.created_at,
            )
        )

    async def read_ai_run(self, run_id: UUID) -> AIRun:
        row = (
            await self._session.execute(select(AIRunRow).where(AIRunRow.id == run_id))
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        return _run_from_row(row)

    async def persist_composition_plan(
        self, plan: PersistedCompositionPlan
    ) -> PersistedCompositionPlan:
        existing = (
            await self._session.execute(
                select(CompositionPlanRow).where(
                    CompositionPlanRow.run_id == plan.run_id,
                    CompositionPlanRow.content_hash == plan.content_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if _plan_provenance_values(existing) != _plan_provenance_values(plan):
                raise ApplicationError(
                    "PLAN_PROVENANCE_CONFLICT",
                    "immutable plan content cannot be replayed with different provenance",
                )
            return plan.model_copy(
                update={"plan_id": existing.id, "created_at": existing.created_at}
            )
        await self._session.execute(insert(CompositionPlanRow).values(**_plan_values(plan)))
        return plan

    async def record_ai_run_event(self, event: AIRunEvent) -> AIRunEvent:
        if event.dedupe_key is not None:
            previous = (
                await self._session.execute(
                    select(AIRunEventRow).where(
                        AIRunEventRow.run_id == event.run_id,
                        AIRunEventRow.event_type == event.event_type,
                        AIRunEventRow.dedupe_key == event.dedupe_key,
                    )
                )
            ).scalar_one_or_none()
            if previous is not None:
                return _event_from_row(previous)
        result = await self._session.execute(
            insert(AIRunEventRow)
            .values(**_event_values(event, sequence=None))
            .returning(AIRunEventRow.sequence)
        )
        return event.model_copy(update={"sequence": result.scalar_one()})

    async def record_ai_run_approval(
        self, *, approval: AIRunApproval, expected_version: int, outbox_event_id: UUID
    ) -> AIRunApproval:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == approval.run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        existing = (
            await self._session.execute(
                select(AIRunApprovalRow).where(AIRunApprovalRow.run_id == approval.run_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            saved = _approval_from_row(existing)
            if (
                saved.assertion_hash != approval.assertion_hash
                or saved.decision != approval.decision
                or saved.actor_id != approval.actor_id
                or saved.expected_plan_content_hash != approval.expected_plan_content_hash
                or saved.interrupt_ref != approval.interrupt_ref
            ):
                raise ApplicationError(
                    "AI_RUN_APPROVAL_CONFLICT", "approval assertion does not match"
                )
            return saved
        if row.version != expected_version or row.status != AIRunStatus.WAITING_APPROVAL.value:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "the AI run cannot accept this approval"
            )
        plan = (
            await self._session.execute(
                select(CompositionPlanRow).where(
                    CompositionPlanRow.run_id == approval.run_id,
                    CompositionPlanRow.content_hash == approval.expected_plan_content_hash,
                )
            )
        ).scalar_one_or_none()
        if plan is None or approval.interrupt_ref != f"plan:{approval.expected_plan_content_hash}":
            raise ApplicationError(
                "AI_RUN_APPROVAL_CONFLICT",
                "approval must bind the persisted pending plan interrupt",
            )
        target = (
            AIRunStatus.MATERIALIZING if approval.decision == "approve" else AIRunStatus.REJECTED
        )
        run = (
            _run_from_row(row)
            .transition(target, now=approval.decided_at)
            .model_copy(update={"approval_assertion_hash": approval.assertion_hash})
        )
        await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run.run_id, AIRunRow.version == expected_version)
            .values(**_run_values(run))
        )
        await self._session.execute(insert(AIRunApprovalRow).values(**_approval_values(approval)))
        if approval.decision == "approve":
            await self._session.execute(
                insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="ai_run",
                aggregate_id=run.run_id,
                topic="graph.resume.requested",
                dedupe_key=f"ai-run:{run.run_id}:approval:{approval.approval_id}",
                payload={
                    "schema_version": "graph-action-request.v1",
                    "run_id": str(run.run_id),
                    "action": "resume",
                },
                status="pending",
                attempts=0,
                available_at=approval.decided_at,
                created_at=approval.decided_at,
                )
            )
        return approval

    async def retry_ai_run(
        self,
        *,
        parent_run_id: UUID,
        expected_version: int,
        idempotency_key: str,
        child_run_id: UUID,
        child_thread_id: str,
        outbox_event_id: UUID,
        now: datetime,
    ) -> AIRun:
        parent_row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == parent_run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if parent_row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        parent = _run_from_row(parent_row)
        existing = (
            await self._session.execute(
                select(AIRunRow).where(
                    AIRunRow.parent_run_id == parent_run_id,
                    AIRunRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _run_from_row(existing)
        if parent.version != expected_version or parent.status not in {
            AIRunStatus.FAILED,
            AIRunStatus.CANCELLED,
        }:
            raise ApplicationError(
                "AI_RUN_ACTION_STATE_CONFLICT", "only a terminal failed/cancelled run can retry"
            )
        child = AIRun(
            run_id=child_run_id,
            parent_run_id=parent.run_id,
            project_id=parent.project_id,
            branch_id=parent.branch_id,
            base_revision_id=parent.base_revision_id,
            thread_id=child_thread_id,
            graph_topology_version=parent.graph_topology_version,
            state_schema_version=parent.state_schema_version,
            brief=parent.brief,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        await self._session.execute(insert(AIRunRow).values(**_run_values(child)))
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="ai_run",
                aggregate_id=child.run_id,
                topic="graph.retry.requested",
                dedupe_key=f"ai-run:{parent_run_id}:retry:{idempotency_key}",
                payload={
                    "schema_version": "graph-start-request.v1",
                    "run_id": str(child.run_id),
                    "parent_run_id": str(parent_run_id),
                    "thread_id": child.thread_id,
                    "run_type": "generate",
                },
                status="pending",
                attempts=0,
                available_at=now,
                created_at=now,
            )
        )
        return child

    async def list_ai_run_events(
        self, run_id: UUID, *, after_sequence: int
    ) -> tuple[AIRunEvent, ...]:
        rows = (
            (
                await self._session.execute(
                    select(AIRunEventRow)
                    .where(AIRunEventRow.run_id == run_id, AIRunEventRow.sequence > after_sequence)
                    .order_by(AIRunEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )
        return tuple(_event_from_row(row) for row in rows)

    async def request_ai_run_action(
        self,
        *,
        run_id: UUID,
        action: str,
        expected_version: int,
        idempotency_key: str,
        outbox_event_id: UUID,
        now: datetime,
    ) -> AIRun:
        if action == "resume":
            raise ApplicationError(
                "AI_RUN_ACTION_INVALID", "approval is the only path that can resume a run"
            )
        if action != "cancel":
            raise ApplicationError("AI_RUN_ACTION_INVALID", "unsupported AI run action")
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        run = _run_from_row(row)
        previous_outbox = (
            await self._session.execute(
                select(OutboxEventRow).where(
                    OutboxEventRow.aggregate_id == run_id,
                    OutboxEventRow.dedupe_key == f"ai-run:{run_id}:{action}:{idempotency_key}",
                )
            )
        ).scalar_one_or_none()
        if previous_outbox is not None:
            return run
        if run.version != expected_version:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "the AI run changed; reload before acting"
            )
        try:
            run = run.transition_for_action(action, now=now)
        except ValueError as exc:
            raise ApplicationError("AI_RUN_ACTION_STATE_CONFLICT", str(exc)) from exc
        await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run_id, AIRunRow.version == expected_version)
            .values(**_run_values(run))
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="ai_run",
                aggregate_id=run_id,
                topic=f"graph.{action}.requested",
                dedupe_key=f"ai-run:{run_id}:{action}:{idempotency_key}",
                payload={
                    "schema_version": "graph-action-request.v1",
                    "run_id": str(run_id),
                    "action": action,
                    "expected_version": expected_version,
                },
                status="pending",
                attempts=0,
                available_at=now,
                created_at=now,
            )
        )
        return run

    async def reserve_model_request(
        self, *, run_id: UUID, kind: ModelRequestKind, reservation_id: UUID, now: datetime
    ) -> ModelRequestReservation:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        prior = (
            (
                await self._session.execute(
                    select(ModelRequestReservationRow.request_kind)
                    .where(ModelRequestReservationRow.run_id == run_id)
                    .order_by(ModelRequestReservationRow.request_ordinal)
                )
            )
            .scalars()
            .all()
        )
        kinds = tuple(ModelRequestKind(item) for item in prior)
        model_request_allowed(
            submitted_model_requests=row.submitted_model_requests,
            prior_request_kinds=kinds,
            requested_kind=kind,
            run_status=AIRunStatus(row.status),
        )
        ordinal = row.submitted_model_requests + 1
        reservation = ModelRequestReservation(
            reservation_id=reservation_id,
            run_id=run_id,
            request_ordinal=ordinal,
            kind=kind,
            created_at=now,
        )
        await self._session.execute(
            insert(ModelRequestReservationRow).values(**_reservation_values(reservation))
        )
        await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run_id)
            .values(submitted_model_requests=ordinal, updated_at=now)
        )
        return reservation

    async def record_model_usage(
        self,
        *,
        run_id: UUID,
        reservation_id: UUID,
        provider_operation_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        now: datetime,
    ) -> ModelRequestReservation:
        row = (
            await self._session.execute(
                select(ModelRequestReservationRow)
                .where(
                    ModelRequestReservationRow.id == reservation_id,
                    ModelRequestReservationRow.run_id == run_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError(
                "MODEL_RESERVATION_NOT_FOUND", "the model reservation does not exist"
            )
        reservation = _reservation_from_row(row)
        if reservation.status is ModelRequestReservationStatus.OBSERVED:
            if (
                reservation.provider_operation_id != provider_operation_id
                or reservation.prompt_tokens != prompt_tokens
                or reservation.completion_tokens != completion_tokens
            ):
                raise ApplicationError(
                    "MODEL_USAGE_CONFLICT",
                    "the reservation is already observed with a different provider operation",
                )
            return reservation
        existing = (
            await self._session.execute(
                select(ModelRequestReservationRow).where(
                    ModelRequestReservationRow.provider_operation_id == provider_operation_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.id != reservation_id:
            raise ApplicationError("MODEL_USAGE_CONFLICT", "provider operation is already recorded")
        observed = reservation.model_copy(
            update={
                "status": ModelRequestReservationStatus.OBSERVED,
                "provider_operation_id": provider_operation_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "observed_at": now,
            }
        )
        await self._session.execute(
            update(ModelRequestReservationRow)
            .where(ModelRequestReservationRow.id == reservation_id)
            .values(**_reservation_values(observed))
        )
        await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run_id)
            .values(
                prompt_tokens=AIRunRow.prompt_tokens + prompt_tokens,
                completion_tokens=AIRunRow.completion_tokens + completion_tokens,
                updated_at=now,
            )
        )
        return observed


def _run_values(run: AIRun) -> dict[str, object]:
    values = run.model_dump(mode="python")
    values["id"] = values.pop("run_id")
    values["brief"] = run.brief
    values["status"] = run.status.value
    values["cost_status"] = run.cost.status.value
    values["cost_microusd"] = run.cost.amount_microusd
    values["pricing_version"] = run.cost.pricing_version
    values.pop("cost")
    return values


def _run_from_row(row: AIRunRow) -> AIRun:
    return AIRun(
        run_id=row.id,
        project_id=row.project_id,
        branch_id=row.branch_id,
        base_revision_id=row.base_revision_id,
        thread_id=row.thread_id,
        parent_run_id=row.parent_run_id,
        graph_topology_version=row.graph_topology_version,
        state_schema_version=row.state_schema_version,
        brief=row.brief,
        status=AIRunStatus(row.status),
        version=row.version,
        idempotency_key=row.idempotency_key,
        approval_assertion_hash=row.approval_assertion_hash,
        submitted_model_requests=row.submitted_model_requests,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        cost=ModelCost(
            status=CostStatus(row.cost_status),
            amount_microusd=row.cost_microusd,
            pricing_version=row.pricing_version,
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        terminal_at=row.terminal_at,
    )


def _plan_values(plan: PersistedCompositionPlan) -> dict[str, object]:
    return {
        "id": plan.plan_id,
        "run_id": plan.run_id,
        "plan": plan.plan.model_dump(mode="json"),
        "content_hash": plan.content_hash,
        "provider": plan.provider,
        "model": plan.model,
        "prompt_version": plan.prompt_version,
        "schema_version": plan.schema_version,
        "style_pack_version": plan.style_pack_version,
        "fallback_reason": plan.fallback_reason,
        "created_at": plan.created_at,
    }


def _plan_from_row(row: CompositionPlanRow) -> PersistedCompositionPlan:
    from motif_forge.agent.schemas import CompositionPlan

    return PersistedCompositionPlan(
        plan_id=row.id,
        run_id=row.run_id,
        plan=CompositionPlan.model_validate(row.plan),
        content_hash=row.content_hash,
        provider=row.provider,
        model=row.model,
        prompt_version=row.prompt_version,
        schema_version=row.schema_version,
        style_pack_version=row.style_pack_version,
        fallback_reason=row.fallback_reason,
        created_at=row.created_at,
    )


def _plan_provenance_values(
    plan: CompositionPlanRow | PersistedCompositionPlan,
) -> tuple[object, ...]:
    return (
        plan.run_id,
        plan.content_hash,
        plan.provider,
        plan.model,
        plan.prompt_version,
        plan.schema_version,
        plan.style_pack_version,
        plan.fallback_reason,
    )


def _event_values(event: AIRunEvent, *, sequence: int | None) -> dict[str, object]:
    del sequence
    return {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "event_type": event.event_type,
        "phase": event.phase,
        "payload": event.payload,
        "dedupe_key": event.dedupe_key,
        "created_at": event.created_at,
    }


def _event_from_row(row: AIRunEventRow) -> AIRunEvent:
    return AIRunEvent(
        sequence=row.sequence,
        event_id=row.event_id,
        run_id=row.run_id,
        event_type=row.event_type,
        phase=row.phase,
        payload=row.payload,
        dedupe_key=row.dedupe_key,
        created_at=row.created_at,
    )


def _reservation_values(reservation: ModelRequestReservation) -> dict[str, object]:
    return {
        "id": reservation.reservation_id,
        "run_id": reservation.run_id,
        "request_ordinal": reservation.request_ordinal,
        "request_kind": reservation.kind.value,
        "status": reservation.status.value,
        "provider_operation_id": reservation.provider_operation_id,
        "prompt_tokens": reservation.prompt_tokens,
        "completion_tokens": reservation.completion_tokens,
        "created_at": reservation.created_at,
        "observed_at": reservation.observed_at,
    }


def _reservation_from_row(row: ModelRequestReservationRow) -> ModelRequestReservation:
    return ModelRequestReservation(
        reservation_id=row.id,
        run_id=row.run_id,
        request_ordinal=row.request_ordinal,
        kind=ModelRequestKind(row.request_kind),
        status=ModelRequestReservationStatus(row.status),
        provider_operation_id=row.provider_operation_id,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        created_at=row.created_at,
        observed_at=row.observed_at,
    )


def _approval_values(approval: AIRunApproval) -> dict[str, object]:
    return {
        "id": approval.approval_id,
        "run_id": approval.run_id,
        "assertion_hash": approval.assertion_hash,
        "decision": approval.decision,
        "actor_id": approval.actor_id,
        "expected_plan_content_hash": approval.expected_plan_content_hash,
        "interrupt_ref": approval.interrupt_ref,
        "decided_at": approval.decided_at,
    }


def _approval_from_row(row: AIRunApprovalRow) -> AIRunApproval:
    return AIRunApproval(
        approval_id=row.id,
        run_id=row.run_id,
        assertion_hash=row.assertion_hash,
        decision=row.decision,
        actor_id=row.actor_id,
        expected_plan_content_hash=row.expected_plan_content_hash,
        interrupt_ref=row.interrupt_ref,
        decided_at=row.decided_at,
    )


def _ai_run_request_hash(row: AIRunRow) -> str:
    from motif_forge.application._hashing import request_hash

    return request_hash(
        {
            "schema": "ai-run.create.v1",
            "project_id": str(row.project_id),
            "branch_id": str(row.branch_id),
            "base_revision_id": str(row.base_revision_id),
            "thread_id": row.thread_id,
            "brief": row.brief,
            "graph_topology_version": row.graph_topology_version,
            "state_schema_version": row.state_schema_version,
        }
    )
