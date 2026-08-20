"""Single-session PostgreSQL transaction for approved composition materialization."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import insert, select

from motif_forge.application.errors import ApplicationError
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunApproval,
    AIRunEvent,
    CompositionMaterializationReceipt,
    PersistedCompositionPlan,
)
from motif_forge.infrastructure.persistence.ai_runs import (
    _approval_from_row,
    _event_from_row,
    _event_values,
    _plan_from_row,
    _run_from_row,
)
from motif_forge.infrastructure.persistence.database import (
    PostgresTransaction,
    SessionFactory,
)
from motif_forge.infrastructure.persistence.tables import (
    AIRunApprovalRow,
    AIRunEventRow,
    AIRunRow,
    CompositionMaterializationReceiptRow,
    CompositionPlanRow,
)


class PostgresCompositionMaterializationUnitOfWork:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresCompositionMaterializationTransaction:
        return PostgresCompositionMaterializationTransaction(self._session_factory())


class PostgresCompositionMaterializationTransaction(PostgresTransaction):
    """Locks AI Run before Branch; every project write shares this session."""

    async def lock_ai_run(self, run_id: UUID) -> AIRun:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        return _run_from_row(row)

    async def read_ai_run_approval(self, run_id: UUID) -> AIRunApproval | None:
        row = (
            await self._session.execute(
                select(AIRunApprovalRow).where(AIRunApprovalRow.run_id == run_id)
            )
        ).scalar_one_or_none()
        return None if row is None else _approval_from_row(row)

    async def read_composition_plan(
        self, *, plan_id: UUID, run_id: UUID
    ) -> PersistedCompositionPlan:
        row = (
            await self._session.execute(
                select(CompositionPlanRow).where(
                    CompositionPlanRow.id == plan_id,
                    CompositionPlanRow.run_id == run_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("PLAN_NOT_FOUND", "the CompositionPlan does not exist")
        return _plan_from_row(row)

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

    async def read_materialization_receipt(
        self, *, run_id: UUID, plan_id: UUID, plan_hash: str, seed: int
    ) -> CompositionMaterializationReceipt | None:
        row = (
            await self._session.execute(
                select(CompositionMaterializationReceiptRow)
                .where(
                    CompositionMaterializationReceiptRow.run_id == run_id,
                    CompositionMaterializationReceiptRow.plan_id == plan_id,
                    CompositionMaterializationReceiptRow.plan_content_hash == plan_hash,
                    CompositionMaterializationReceiptRow.seed == seed,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        return None if row is None else _receipt_from_row(row)

    async def insert_materialization_receipt(
        self, receipt: CompositionMaterializationReceipt, event: AIRunEvent
    ) -> None:
        await self._session.execute(
            insert(CompositionMaterializationReceiptRow).values(
                id=receipt.receipt_id,
                schema_version=receipt.schema_version,
                run_id=receipt.run_id,
                plan_id=receipt.plan_id,
                plan_content_hash=receipt.plan_content_hash,
                plan_hash_version=receipt.plan_hash_version,
                seed=receipt.seed,
                request_hash=receipt.request_hash,
                actor_id=receipt.actor_id,
                assertion_hash=receipt.assertion_hash,
                candidate_snapshot_id=receipt.candidate_snapshot_id,
                preview_id=receipt.preview_id,
                revision_id=receipt.revision_id,
                command_batch_id=receipt.command_batch_id,
                style_pack_version=receipt.style_pack_version,
                compiler_version=receipt.compiler_version,
                created_at=receipt.created_at,
            )
        )
        await self._session.execute(
            insert(AIRunEventRow).values(**_event_values(event, sequence=None))
        )


def _receipt_from_row(
    row: CompositionMaterializationReceiptRow,
) -> CompositionMaterializationReceipt:
    return CompositionMaterializationReceipt(
        schema_version=cast(Literal["composition-materialization-receipt.v1"], row.schema_version),
        receipt_id=row.id,
        run_id=row.run_id,
        plan_id=row.plan_id,
        plan_content_hash=row.plan_content_hash,
        plan_hash_version=cast(
            Literal["composition-plan-hash.rounded-v1", "composition-plan-hash.lossless-v2"],
            row.plan_hash_version,
        ),
        seed=row.seed,
        request_hash=row.request_hash,
        actor_id=row.actor_id,
        assertion_hash=row.assertion_hash,
        candidate_snapshot_id=row.candidate_snapshot_id,
        preview_id=row.preview_id,
        revision_id=row.revision_id,
        command_batch_id=row.command_batch_id,
        style_pack_version=cast(Literal["synth-ambient.v1"], row.style_pack_version),
        compiler_version=row.compiler_version,
        created_at=row.created_at,
    )
