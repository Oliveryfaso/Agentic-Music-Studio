"""PostgreSQL implementation of the durable S2 AI-run ledger."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from motif_forge.application.ai_runs import model_request_allowed
from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import IdempotencyHit
from motif_forge.domain.ai_runs import (
    AIRun,
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
    AIRunEventRow,
    AIRunRow,
    CompositionPlanRow,
    IdempotencyRow,
    ModelRequestReservationRow,
    OutboxEventRow,
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
                select(IdempotencyRow).where(
                    IdempotencyRow.operation == "ai-run.create.v1",
                    IdempotencyRow.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.result_payload.get("project_id") != str(project_id):
            return None
        return IdempotencyHit(
            resource_id=row.resource_id,
            request_hash=row.request_hash,
            result_payload=row.result_payload,
        )

    async def create_ai_run(
        self, *, run: AIRun, created_event: AIRunEvent, outbox_event_id: UUID, request_hash: str
    ) -> None:
        await self._session.execute(insert(AIRunRow).values(**_run_values(run)))
        await self._session.execute(
            insert(AIRunEventRow).values(**_event_values(created_event, sequence=None))
        )
        await self._session.execute(
            insert(IdempotencyRow).values(
                operation="ai-run.create.v1",
                idempotency_key=run.idempotency_key,
                request_hash=request_hash,
                resource_id=run.run_id,
                result_payload={"run_id": str(run.run_id), "project_id": str(run.project_id)},
                created_at=run.created_at,
            )
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
            return _plan_from_row(existing)
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
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        run = _run_from_row(row)
        if run.version != expected_version:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "the AI run changed; reload before acting"
            )
        if action == "cancel":
            run = run.transition(AIRunStatus.CANCELLED, now=now)
        else:
            run = run.model_copy(update={"version": run.version + 1, "updated_at": now})
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
            if reservation.provider_operation_id != provider_operation_id:
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
