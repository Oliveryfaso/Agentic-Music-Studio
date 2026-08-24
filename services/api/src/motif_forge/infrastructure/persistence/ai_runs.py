"""PostgreSQL implementation of the durable S2 AI-run ledger."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motif_forge.application.ai_runs import model_request_allowed
from motif_forge.application.errors import ApplicationError, IdempotencyKeyReusedError
from motif_forge.application.ports import (
    AIRunCandidateProjection,
    AIRunEditPreviewProjection,
    AIRunProgress,
    AIRunProjection,
    IdempotencyHit,
)
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunApproval,
    AIRunEvent,
    AIRunStatus,
    AIRunType,
    CostStatus,
    ModelCost,
    ModelRequestKind,
    ModelRequestReservation,
    ModelRequestReservationStatus,
    ModelUsageStatus,
    PersistedCompositionPlan,
    PlanHashVersion,
    composition_plan_content_hash,
)
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import (
    AIRunActionIdempotencyRow,
    AIRunApprovalRow,
    AIRunEditDecisionRow,
    AIRunEventRow,
    AIRunRow,
    AudioArtifactRow,
    BranchRow,
    CandidateSnapshotRow,
    CompositionMaterializationReceiptRow,
    CompositionPlanRow,
    ExportBundleArtifactRow,
    MediaJobRow,
    MediaRunRow,
    ModelRequestReservationRow,
    OutboxEventRow,
    PreviewCandidateRow,
    RevisionRow,
)

_COMPLETE_EXPORT_STEPS = (
    "master",
    "stem:pad",
    "stem:melody",
    "stem:bass",
    "stem:rhythm",
    "mp3",
    "bundle",
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

    async def get_ai_run_action_idempotency(
        self, *, parent_run_id: UUID, action: str, key: str
    ) -> IdempotencyHit | None:
        row = (
            await self._session.execute(
                select(AIRunActionIdempotencyRow).where(
                    AIRunActionIdempotencyRow.parent_run_id == parent_run_id,
                    AIRunActionIdempotencyRow.action == action,
                    AIRunActionIdempotencyRow.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return IdempotencyHit(
            resource_id=row.result_run_id, request_hash=row.request_hash,
            result_payload={"run_id": str(row.result_run_id)},
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
                    "schema_version": "graph-action.v1",
                    "action": "start",
                    "run_id": str(run.run_id),
                    "thread_id": run.thread_id,
                    "run_type": (
                        "parent.edit.v1" if run.run_type.value == "edit" else "parent.generate.v1"
                    ),
                    "decision": None,
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

    async def read_ai_run_by_thread_id(self, thread_id: str) -> AIRun:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.thread_id == thread_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        return _run_from_row(row)

    async def read_ai_run_projection(self, run_id: UUID) -> AIRunProjection:
        run = await self.read_ai_run(run_id)
        receipt = (
            await self._session.execute(
                select(CompositionMaterializationReceiptRow)
                .where(CompositionMaterializationReceiptRow.run_id == run_id)
                .order_by(CompositionMaterializationReceiptRow.created_at.desc())
            )
        ).scalars().first()
        bundle = None
        if receipt is not None:
            bundle = (
                await self._session.execute(
                    select(ExportBundleArtifactRow)
                    .where(ExportBundleArtifactRow.revision_id == receipt.revision_id)
                    .order_by(ExportBundleArtifactRow.created_at.desc())
                )
            ).scalars().first()
        plan = (
            await self._session.execute(
                select(CompositionPlanRow)
                .where(CompositionPlanRow.run_id == run_id)
                .order_by(CompositionPlanRow.created_at.desc())
            )
        ).scalars().first()
        ai_run_events = (
            (
                await self._session.execute(
                    select(AIRunEventRow)
                    .where(AIRunEventRow.run_id == run_id)
                    .order_by(AIRunEventRow.sequence.desc())
                )
            ).scalars().all()
        )
        error_code = next(
            (str(event.payload["error_code"]) for event in ai_run_events
             if isinstance(event.payload.get("error_code"), str)), None
        )
        media_run = (
            await self._session.execute(
                select(MediaRunRow)
                .where(
                    MediaRunRow.project_id == run.project_id,
                    MediaRunRow.thread_id == run.thread_id,
                    MediaRunRow.run_type == "complete_song_export.v1",
                )
                .order_by(MediaRunRow.created_at.desc(), MediaRunRow.id.desc())
            )
        ).scalars().first()
        completed_count = 0
        if media_run is not None:
            jobs = (
                (
                    await self._session.execute(
                        select(MediaJobRow)
                        .where(MediaJobRow.run_id == media_run.id)
                        .order_by(MediaJobRow.created_at, MediaJobRow.id)
                    )
                ).scalars().all()
            )
            for job in jobs[: len(_COMPLETE_EXPORT_STEPS)]:
                if job.status != "succeeded":
                    break
                completed_count += 1
        created_labels: dict[UUID, str] = {}
        for event in reversed(ai_run_events):
            if event.event_type != "composition.candidate-created":
                continue
            try:
                created_labels[UUID(str(event.payload["candidate_id"]))] = str(
                    event.payload["label"]
                )
            except (KeyError, ValueError):
                continue
        preview_rows = (
            (
                await self._session.execute(
                    select(PreviewCandidateRow)
                    .where(PreviewCandidateRow.source_run_id == run_id)
                    .order_by(PreviewCandidateRow.created_at, PreviewCandidateRow.id)
                )
            ).scalars().all()
        )
        candidates: list[AIRunCandidateProjection] = []
        for preview in preview_rows:
            snapshot = (
                await self._session.execute(
                    select(CandidateSnapshotRow).where(
                        CandidateSnapshotRow.id == preview.candidate_snapshot_id
                    )
                )
            ).scalar_one_or_none()
            if snapshot is None or snapshot.candidate_id not in created_labels:
                continue
            label = created_labels[snapshot.candidate_id]
            if label not in {"a", "b"} or not preview.preview_artifact_ids:
                continue
            try:
                artifact_id = UUID(preview.preview_artifact_ids[0])
            except (ValueError, TypeError):
                continue
            artifact = (
                await self._session.execute(
                    select(AudioArtifactRow).where(
                        AudioArtifactRow.id == artifact_id,
                        AudioArtifactRow.candidate_snapshot_id == snapshot.id,
                        AudioArtifactRow.quality_profile == "candidate-preview.v1",
                    )
                )
            ).scalar_one_or_none()
            if artifact is None:
                continue
            repair_status = "improved" if snapshot.parent_candidate_snapshot_id else "not_requested"
            if repair_status == "not_requested" and any(
                event.event_type == "candidate.repair.non_improving"
                and event.payload.get("selected_snapshot_id") == str(snapshot.id)
                for event in ai_run_events
            ):
                repair_status = "non_improving"
            candidates.append(AIRunCandidateProjection(
                label=cast(Any, label), candidate_id=snapshot.candidate_id,
                candidate_snapshot_id=snapshot.id,
                candidate_content_hash=snapshot.candidate_content_hash,
                preview_id=preview.id, preview_artifact_id=artifact.id,
                preview_availability=cast(Any, artifact.availability),
                parent_candidate_snapshot_id=snapshot.parent_candidate_snapshot_id,
                repair_status=cast(Any, repair_status),
            ))
        candidates.sort(key=lambda item: item.label)
        critique_event = next(
            (event for event in ai_run_events if event.event_type == "candidate.critic.completed"),
            None,
        )
        edit_preview = None
        if run.pending_preview_id is not None:
            preview_row = await self._session.scalar(
                select(PreviewCandidateRow).where(
                    PreviewCandidateRow.id == run.pending_preview_id,
                    PreviewCandidateRow.source_run_id == run_id,
                )
            )
            if preview_row is not None:
                edit_artifact_id: UUID | None = None
                availability = "missing"
                if preview_row.preview_artifact_ids:
                    try:
                        edit_artifact_id = UUID(preview_row.preview_artifact_ids[0])
                    except (TypeError, ValueError):
                        edit_artifact_id = None
                    if edit_artifact_id is not None:
                        artifact_row = await self._session.scalar(
                            select(AudioArtifactRow).where(
                                AudioArtifactRow.id == edit_artifact_id
                            )
                        )
                        if artifact_row is not None:
                            availability = artifact_row.availability
                edit_preview = AIRunEditPreviewProjection(
                    preview_id=preview_row.id,
                    candidate_snapshot_id=preview_row.candidate_snapshot_id,
                    candidate_content_hash=preview_row.candidate_content_hash,
                    preview_artifact_id=edit_artifact_id,
                    preview_availability=cast(Any, availability),
                    actual_change_impact=preview_row.actual_change_impact,
                    structural_diff=tuple(preview_row.structural_diff),
                )
        return AIRunProjection(
            run=run, plan=_plan_from_row(plan) if plan else None,
            progress=AIRunProgress(
                phase=run.status,
                completed_export_steps=_COMPLETE_EXPORT_STEPS[:completed_count],
                total_export_steps=len(_COMPLETE_EXPORT_STEPS),
                latest_event_sequence=(ai_run_events[0].sequence if ai_run_events else 0),
                error_code=error_code,
            ),
            revision_id=(
                receipt.revision_id if receipt else run.materialized_revision_id
            ),
            bundle_id=bundle.id if bundle else None,
            fallback_reason=plan.fallback_reason if plan else None, error_code=error_code,
            candidates=tuple(candidates),
            critique=dict(critique_event.payload) if critique_event else None,
            selected_candidate_id=(
                receipt.candidate_snapshot_id and next(
                    (
                        item.candidate_id for item in candidates
                        if item.candidate_snapshot_id == receipt.candidate_snapshot_id
                    ),
                    None,
                )
                if receipt else None
            ),
            selected_preview_id=receipt.preview_id if receipt else None,
            candidate_selection_requested=any(
                event.event_type == "candidate.selection.requested"
                for event in ai_run_events
            ),
            edit_preview=edit_preview,
        )

    async def record_idempotent_candidate_selection(
        self, *, run_id: UUID, actor_id: str, decision: str, assertion: str,
        selected_preview_id: UUID | None, expected_candidate_id: UUID | None,
        expected_candidate_content_hash: str | None, note: str,
        expected_version: int, idempotency_key: str, request_hash: str,
        outbox_event_id: UUID, event_id: UUID, now: datetime,
    ) -> None:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        if row.version != expected_version:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "candidate selection used a stale Run version"
            )
        result = await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run_id, AIRunRow.version == expected_version)
            .values(version=expected_version + 1, updated_at=now)
        )
        if cast(Any, result).rowcount != 1:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "candidate selection lost its Run version race"
            )
        await self._session.execute(insert(AIRunActionIdempotencyRow).values(
            id=UUID(bytes=secrets.token_bytes(16)), parent_run_id=run_id,
            action="select_candidate", idempotency_key=idempotency_key,
            request_hash=request_hash, result_run_id=run_id, created_at=now,
        ))
        decision_payload = {
            "decision": decision, "actor_id": actor_id,
            "selection_assertion": assertion,
            "selected_preview_id": str(selected_preview_id) if selected_preview_id else None,
            "expected_candidate_id": str(expected_candidate_id) if expected_candidate_id else None,
            "expected_candidate_content_hash": expected_candidate_content_hash,
            "note": note,
        }
        await self._session.execute(insert(AIRunEventRow).values(**_event_values(
            AIRunEvent(
                sequence=1, event_id=event_id, run_id=run_id,
                event_type="candidate.selection.requested", phase="waiting_candidate_selection",
                payload=cast(dict[str, object], decision_payload),
                dedupe_key=f"candidate-selection:{idempotency_key}", created_at=now,
            ),
            sequence=None,
        )))
        await self._session.execute(insert(OutboxEventRow).values(
            id=outbox_event_id, aggregate_type="ai_run", aggregate_id=run_id,
            topic="graph.resume.requested",
            dedupe_key=f"ai-run:{run_id}:candidate-selection:{idempotency_key}",
            payload={
                "schema_version": "graph-action.v1", "action": "resume",
                "run_id": str(run_id), "thread_id": row.thread_id,
                "run_type": "parent.generate.v1", "decision": decision_payload,
            },
            status="pending", attempts=0, available_at=now, created_at=now,
        ))

    async def record_idempotent_ai_run_approval(
        self, *, approval: AIRunApproval, assertion: str, note: str,
        expected_version: int, idempotency_key: str, request_hash: str,
        outbox_event_id: UUID,
    ) -> AIRunApproval:
        existing_key = (
            await self._session.execute(
                select(AIRunActionIdempotencyRow).where(
                    AIRunActionIdempotencyRow.parent_run_id == approval.run_id,
                    AIRunActionIdempotencyRow.action == "resume",
                    AIRunActionIdempotencyRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing_key is not None:
            if existing_key.request_hash != request_hash:
                raise IdempotencyKeyReusedError
            saved = await self.read_ai_run_approval(approval.run_id)
            if saved is None:
                raise ApplicationError("PERSISTENCE_INVARIANT_VIOLATION", "resume replay missing")
            return saved
        saved = await self.record_ai_run_approval(
            approval=approval, assertion=assertion, note=note,
            expected_version=expected_version, outbox_event_id=outbox_event_id,
        )
        await self._session.execute(insert(AIRunActionIdempotencyRow).values(
            id=UUID(bytes=secrets.token_bytes(16)), parent_run_id=approval.run_id,
            action="resume", idempotency_key=idempotency_key, request_hash=request_hash,
            result_run_id=approval.run_id, created_at=approval.decided_at,
        ))
        return saved

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
            return _plan_from_row(existing)
        await self._session.execute(insert(CompositionPlanRow).values(**_plan_values(plan)))
        return plan

    async def persist_plan_and_mark_pending(
        self,
        *,
        plan: PersistedCompositionPlan,
        expected_version: int,
        now: datetime,
    ) -> tuple[PersistedCompositionPlan, AIRun]:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == plan.run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        await self._session.execute(
            pg_insert(CompositionPlanRow)
            .values(**_plan_values(plan))
            .on_conflict_do_nothing(
                index_elements=[CompositionPlanRow.run_id, CompositionPlanRow.content_hash]
            )
        )
        plan_row = (
            await self._session.execute(
                select(CompositionPlanRow)
                .where(
                    CompositionPlanRow.run_id == plan.run_id,
                    CompositionPlanRow.content_hash == plan.content_hash,
                )
                .with_for_update()
            )
        ).scalar_one()
        persisted = _plan_from_row(plan_row)
        if _plan_provenance_values(plan_row) != _plan_provenance_values(plan):
            raise ApplicationError(
                "PLAN_PROVENANCE_CONFLICT",
                "immutable plan content cannot be replayed with different provenance",
            )
        current = _run_from_row(row)
        if current.status is AIRunStatus.WAITING_APPROVAL:
            if (
                current.pending_plan_id == persisted.plan_id
                and current.pending_plan_content_hash == persisted.content_hash
            ):
                return persisted, current
            raise ApplicationError(
                "AI_RUN_PLAN_CONFLICT", "the AI run is waiting for a different Plan"
            )
        if current.version != expected_version or current.status not in {
            AIRunStatus.QUEUED,
            AIRunStatus.PLANNING,
        }:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "the AI run cannot wait for this plan"
            )
        run = current.model_copy(
            update={
                "status": AIRunStatus.WAITING_APPROVAL,
                "version": current.version + 1,
                "updated_at": now,
                "pending_plan_id": persisted.plan_id,
                "pending_plan_content_hash": persisted.content_hash,
                "pending_interrupt_ref": secrets.token_urlsafe(32),
            }
        )
        await self._session.execute(
            update(AIRunRow).where(AIRunRow.id == run.run_id).values(**_run_values(run))
        )
        return persisted, run

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

    async def read_ai_run_approval(self, run_id: UUID) -> AIRunApproval | None:
        row = (
            await self._session.execute(
                select(AIRunApprovalRow).where(AIRunApprovalRow.run_id == run_id)
            )
        ).scalar_one_or_none()
        return None if row is None else _approval_from_row(row)

    async def mark_ai_run_plan_pending(
        self, *, run_id: UUID, plan_id: UUID, expected_version: int, now: datetime
    ) -> AIRun:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        plan = (
            await self._session.execute(
                select(CompositionPlanRow).where(
                    CompositionPlanRow.id == plan_id, CompositionPlanRow.run_id == run_id
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "the AI run cannot wait for this plan"
            )
        current = _run_from_row(row)
        if current.status is AIRunStatus.WAITING_APPROVAL:
            if (
                current.pending_plan_id == plan.id
                and current.pending_plan_content_hash == plan.content_hash
            ):
                return current
            raise ApplicationError(
                "AI_RUN_PLAN_CONFLICT",
                "the AI run is already waiting for a different CompositionPlan",
            )
        if row.version != expected_version:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "the AI run cannot wait for this plan"
            )
        if current.status not in {
            AIRunStatus.QUEUED,
            AIRunStatus.PLANNING,
            AIRunStatus.WAITING_APPROVAL,
        }:
            raise ApplicationError(
                "AI_RUN_ACTION_STATE_CONFLICT", "only a planning run can wait for a plan"
            )
        run = current.model_copy(
            update={
                "status": AIRunStatus.WAITING_APPROVAL,
                "version": current.version + 1,
                "updated_at": now,
                "pending_plan_id": plan.id,
                "pending_plan_content_hash": plan.content_hash,
                "pending_interrupt_ref": secrets.token_urlsafe(32),
            }
        )
        await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run_id, AIRunRow.version == expected_version)
            .values(**_run_values(run))
        )
        return run

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

    async def record_ai_run_graph_progress(
        self,
        *,
        run_id: UUID,
        target_status: AIRunStatus,
        error_code: str | None,
        materialized_revision_id: UUID | None,
        event_id: UUID,
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
        if run.status is target_status:
            return run
        if run.status in {
            AIRunStatus.SUCCEEDED,
            AIRunStatus.REJECTED,
            AIRunStatus.FAILED,
            AIRunStatus.CANCELLED,
        }:
            raise ApplicationError(
                "AI_RUN_GRAPH_PROGRESS_CONFLICT",
                "terminal AI Run status disagrees with the Parent Graph",
            )
        original_version = run.version
        try:
            if target_status is AIRunStatus.WAITING_EDIT_APPROVAL:
                if run.status is AIRunStatus.QUEUED:
                    run = run.transition(AIRunStatus.PLANNING, now=now)
                run = run.transition(AIRunStatus.WAITING_EDIT_APPROVAL, now=now)
            elif target_status is AIRunStatus.WAITING_WORKER:
                if run.run_type is AIRunType.EDIT and run.status is AIRunStatus.QUEUED:
                    run = run.transition(AIRunStatus.PLANNING, now=now)
                run = run.transition(AIRunStatus.WAITING_WORKER, now=now)
            elif target_status is AIRunStatus.SUCCEEDED:
                if run.run_type is AIRunType.EDIT and run.status is AIRunStatus.QUEUED:
                    run = run.transition(AIRunStatus.PLANNING, now=now)
                if run.status is AIRunStatus.MATERIALIZING:
                    run = run.transition(AIRunStatus.WAITING_WORKER, now=now)
                run = run.transition(AIRunStatus.SUCCEEDED, now=now)
            elif target_status is AIRunStatus.FAILED:
                run = run.transition(AIRunStatus.FAILED, now=now)
            elif target_status in {AIRunStatus.REJECTED, AIRunStatus.CANCELLED}:
                run = run.transition(target_status, now=now)
            else:
                raise ValueError("unsupported Graph progress target")
        except ValueError as exc:
            raise ApplicationError(
                "AI_RUN_GRAPH_PROGRESS_CONFLICT",
                "Parent Graph progress is incompatible with the AI Run ledger",
            ) from exc
        if materialized_revision_id is not None:
            revision_exists = await self._session.scalar(
                select(RevisionRow.id).where(
                    RevisionRow.id == materialized_revision_id,
                    RevisionRow.project_id == run.project_id,
                )
            )
            if revision_exists is None:
                raise ApplicationError(
                    "EDIT_REVISION_LINEAGE_MISMATCH",
                    "Graph result Revision does not belong to the Edit Run project",
                )
            run = run.model_copy(
                update={"materialized_revision_id": materialized_revision_id}
            )
        result = await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run_id, AIRunRow.version == original_version)
            .values(**_run_values(run))
        )
        if cast(Any, result).rowcount != 1:
            raise ApplicationError(
                "AI_RUN_VERSION_CONFLICT", "the AI run changed during Graph progress"
            )
        payload: dict[str, object] = {"status": target_status.value}
        if error_code is not None:
            payload["error_code"] = error_code
        await self._session.execute(
            insert(AIRunEventRow).values(
                event_id=event_id,
                run_id=run_id,
                event_type=f"ai_run.{target_status.value}",
                phase=target_status.value,
                payload=payload,
                dedupe_key=f"graph-progress:{target_status.value}",
                created_at=now,
            )
        )
        return run

    async def mark_edit_preview_pending(
        self, *, run_id: UUID, preview_id: UUID, now: datetime
    ) -> AIRun:
        row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        run = _run_from_row(row)
        if run.status is AIRunStatus.WAITING_EDIT_APPROVAL:
            if run.pending_preview_id != preview_id:
                raise ApplicationError(
                    "EDIT_PREVIEW_IDENTITY_CONFLICT", "Run waits on another Preview"
                )
            return run
        if run.run_type is not AIRunType.EDIT:
            raise ApplicationError("AI_RUN_TYPE_INVALID", "only Edit Runs accept edit Preview")
        if run.status is AIRunStatus.QUEUED:
            run = run.transition(AIRunStatus.PLANNING, now=now)
        run = run.model_copy(update={"pending_preview_id": preview_id})
        run = run.transition(AIRunStatus.WAITING_EDIT_APPROVAL, now=now)
        await self._session.execute(
            update(AIRunRow).where(AIRunRow.id == run_id).values(**_run_values(run))
        )
        return run

    async def read_edit_preview_decision(self, run_id: UUID) -> dict[str, object] | None:
        row = (
            await self._session.execute(
                select(AIRunEditDecisionRow).where(AIRunEditDecisionRow.run_id == run_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "run_id": row.run_id,
            "preview_id": row.preview_id,
            "action": row.action,
            "expected_candidate_content_hash": row.expected_candidate_content_hash,
            "actor_id": row.actor_id,
            "assertion_hash": row.assertion_hash,
            "idempotency_key": row.idempotency_key,
            "request_hash": row.request_hash,
            "note": row.note,
        }

    async def record_edit_preview_decision(
        self,
        *,
        decision_id: UUID,
        run_id: UUID,
        preview_id: UUID,
        action: str,
        expected_candidate_content_hash: str,
        actor_id: str,
        assertion_hash: str,
        assertion: str,
        idempotency_key: str,
        request_hash: str,
        note: str,
        outbox_event_id: UUID,
        now: datetime,
    ) -> None:
        run_row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run_row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        run = _run_from_row(run_row)
        if (
            run.status is not AIRunStatus.WAITING_EDIT_APPROVAL
            or run.pending_preview_id != preview_id
        ):
            raise ApplicationError(
                "EDIT_PREVIEW_STATE_CONFLICT",
                "Run is not waiting on the requested Preview",
            )
        await self._session.execute(
            insert(AIRunEditDecisionRow).values(
                id=decision_id,
                run_id=run_id,
                preview_id=preview_id,
                action=action,
                expected_candidate_content_hash=expected_candidate_content_hash,
                actor_id=actor_id,
                assertion_hash=assertion_hash,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                note=note,
                created_at=now,
            )
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="ai_run",
                aggregate_id=run_id,
                topic="graph.resume.requested",
                dedupe_key=f"ai-run:{run_id}:edit-preview-decision",
                payload={
                    "schema_version": "graph-action.v1",
                    "action": "resume",
                    "run_id": str(run_id),
                    "thread_id": run.thread_id,
                    "run_type": "parent.edit.v1",
                    "decision": {
                        "action": action,
                        "preview_id": str(preview_id),
                        "expected_candidate_content_hash": expected_candidate_content_hash,
                        "actor_id": actor_id,
                        "approval_assertion": assertion,
                        "note": note,
                    },
                },
                status="pending",
                attempts=0,
                available_at=now,
                created_at=now,
            )
        )

    async def record_ai_run_approval(
        self,
        *,
        approval: AIRunApproval,
        assertion: str,
        note: str,
        expected_version: int,
        outbox_event_id: UUID,
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
        if (
            row.pending_plan_id is None
            or row.pending_plan_content_hash != approval.expected_plan_content_hash
            or row.pending_interrupt_ref != approval.interrupt_ref
        ):
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
            .model_copy(
                update={
                    "approval_assertion_hash": approval.assertion_hash,
                    "pending_plan_id": None,
                    "pending_plan_content_hash": None,
                    "pending_interrupt_ref": None,
                }
            )
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
                        "schema_version": "graph-action.v1",
                        "run_id": str(run.run_id),
                        "action": "resume",
                        "thread_id": run.thread_id,
                        "run_type": "parent.generate.v1",
                        "decision": {
                            "decision": approval.decision,
                            "actor_id": approval.actor_id,
                            "approval_assertion": assertion,
                            "expected_plan_hash": approval.expected_plan_content_hash,
                            "note": note,
                        },
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
        created_event_id: UUID,
        outbox_event_id: UUID,
        request_hash: str,
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
                select(AIRunActionIdempotencyRow).where(
                    AIRunActionIdempotencyRow.parent_run_id == parent_run_id,
                    AIRunActionIdempotencyRow.action == "retry",
                    AIRunActionIdempotencyRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyKeyReusedError
            return await self.read_ai_run(existing.result_run_id)
        if parent.version != expected_version or parent.status not in {
            AIRunStatus.FAILED,
            AIRunStatus.CANCELLED,
        }:
            raise ApplicationError(
                "AI_RUN_ACTION_STATE_CONFLICT", "only a terminal failed/cancelled run can retry"
            )
        branch = (
            await self._session.execute(
                select(BranchRow)
                .where(BranchRow.id == parent.branch_id, BranchRow.project_id == parent.project_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if branch is None:
            raise ApplicationError("AI_RUN_IDENTITY_INVALID", "the parent branch is unavailable")
        child = AIRun(
            run_id=child_run_id,
            parent_run_id=parent.run_id,
            project_id=parent.project_id,
            branch_id=parent.branch_id,
            base_revision_id=branch.head_revision_id,
            thread_id=child_thread_id,
            graph_topology_version=parent.graph_topology_version,
            state_schema_version=parent.state_schema_version,
            brief=parent.brief,
            idempotency_key=None,
            created_at=now,
            updated_at=now,
        )
        await self._session.execute(insert(AIRunRow).values(**_run_values(child)))
        await self._session.execute(
            insert(AIRunEventRow).values(
                **_event_values(
                    AIRunEvent(
                        sequence=1,
                        event_id=created_event_id,
                        run_id=child.run_id,
                        event_type="ai_run.created",
                        phase="queued",
                        payload={"thread_id": child.thread_id, "parent_run_id": str(parent_run_id)},
                        dedupe_key="created",
                        created_at=now,
                    ),
                    sequence=None,
                )
            )
        )
        await self._session.execute(
            insert(AIRunActionIdempotencyRow).values(
                id=UUID(bytes=secrets.token_bytes(16)),
                parent_run_id=parent_run_id,
                action="retry",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result_run_id=child.run_id,
                created_at=now,
            )
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="ai_run",
                aggregate_id=child.run_id,
                topic="graph.start.requested",
                dedupe_key=f"ai-run:{parent_run_id}:retry:{idempotency_key}",
                payload={
                    "schema_version": "graph-action.v1",
                    "action": "start",
                    "run_id": str(child.run_id),
                    "thread_id": child.thread_id,
                    "run_type": "parent.generate.v1",
                    "decision": None,
                },
                status="pending",
                attempts=0,
                available_at=now,
                created_at=now,
            )
        )
        return child

    async def replan_ai_run(
        self,
        *,
        parent_run_id: UUID,
        expected_version: int,
        expected_plan_hash: str,
        idempotency_key: str,
        child_run_id: UUID,
        child_thread_id: str,
        child_brief: dict[str, object],
        created_event_id: UUID,
        outbox_event_id: UUID,
        request_hash: str,
        now: datetime,
    ) -> AIRun:
        parent_row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == parent_run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if parent_row is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI run does not exist")
        existing = (
            await self._session.execute(
                select(AIRunActionIdempotencyRow).where(
                    AIRunActionIdempotencyRow.parent_run_id == parent_run_id,
                    AIRunActionIdempotencyRow.action == "replan",
                    AIRunActionIdempotencyRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyKeyReusedError
            return await self.read_ai_run(existing.result_run_id)

        parent = _run_from_row(parent_row)
        if (
            parent.status is not AIRunStatus.WAITING_APPROVAL
            or parent.version != expected_version
            or parent.pending_plan_id is None
            or parent.pending_plan_content_hash != expected_plan_hash
        ):
            raise ApplicationError(
                "AI_RUN_REPLAN_STATE_CONFLICT",
                "replan requires the current pending Plan version and content hash",
            )
        persisted_plan = (
            await self._session.execute(
                select(CompositionPlanRow).where(
                    CompositionPlanRow.id == parent.pending_plan_id,
                    CompositionPlanRow.run_id == parent.run_id,
                    CompositionPlanRow.content_hash == expected_plan_hash,
                )
            )
        ).scalar_one_or_none()
        if persisted_plan is None:
            raise ApplicationError(
                "AI_RUN_REPLAN_STATE_CONFLICT",
                "the pending Plan is no longer available for replan",
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
            brief=child_brief,
            max_model_requests=parent.max_model_requests,
            max_total_tokens=parent.max_total_tokens,
            created_at=now,
            updated_at=now,
        )
        await self._session.execute(insert(AIRunRow).values(**_run_values(child)))
        await self._session.execute(
            insert(AIRunEventRow).values(
                **_event_values(
                    AIRunEvent(
                        sequence=1,
                        event_id=created_event_id,
                        run_id=child.run_id,
                        event_type="ai_run.created",
                        phase="queued",
                        payload={
                            "thread_id": child.thread_id,
                            "parent_run_id": str(parent_run_id),
                        },
                        dedupe_key="created",
                        created_at=now,
                    ),
                    sequence=None,
                )
            )
        )
        await self._session.execute(
            insert(AIRunActionIdempotencyRow).values(
                id=UUID(bytes=secrets.token_bytes(16)),
                parent_run_id=parent_run_id,
                action="replan",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result_run_id=child.run_id,
                created_at=now,
            )
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="ai_run",
                aggregate_id=child.run_id,
                topic="graph.start.requested",
                dedupe_key=f"ai-run:{parent_run_id}:replan:{idempotency_key}",
                payload={
                    "schema_version": "graph-action.v1",
                    "action": "start",
                    "run_id": str(child.run_id),
                    "thread_id": child.thread_id,
                    "run_type": "parent.generate.v1",
                    "decision": None,
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
                    "schema_version": "graph-action.v1",
                    "run_id": str(run_id),
                    "action": action,
                    "thread_id": run.thread_id,
                    "run_type": "parent.generate.v1",
                    "decision": None,
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
            max_model_requests=row.max_model_requests,
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
        usage_status: ModelUsageStatus,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        prompt_cache_hit_tokens: int | None,
        prompt_cache_miss_tokens: int | None,
        reasoning_tokens: int | None,
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
                or reservation.usage_status != usage_status
                or reservation.total_tokens != total_tokens
                or reservation.prompt_cache_hit_tokens != prompt_cache_hit_tokens
                or reservation.prompt_cache_miss_tokens != prompt_cache_miss_tokens
                or reservation.reasoning_tokens != reasoning_tokens
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
                "usage_status": usage_status,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "prompt_cache_hit_tokens": prompt_cache_hit_tokens,
                "prompt_cache_miss_tokens": prompt_cache_miss_tokens,
                "reasoning_tokens": reasoning_tokens,
                "observed_at": now,
            }
        )
        await self._session.execute(
            update(ModelRequestReservationRow)
            .where(ModelRequestReservationRow.id == reservation_id)
            .values(**_reservation_values(observed))
        )

        def aggregate(previous: int | None, current: int | None) -> int | None:
            return previous + current if previous is not None and current is not None else None

        run_row = (
            await self._session.execute(
                select(AIRunRow).where(AIRunRow.id == run_id).with_for_update()
            )
        ).scalar_one()
        prior_status = ModelUsageStatus(run_row.model_usage_status)
        aggregate_status = (
            ModelUsageStatus.UNKNOWN
            if ModelUsageStatus.UNKNOWN in {prior_status, usage_status}
            else ModelUsageStatus.PARTIAL
            if ModelUsageStatus.PARTIAL in {prior_status, usage_status}
            else ModelUsageStatus.KNOWN
        )
        await self._session.execute(
            update(AIRunRow)
            .where(AIRunRow.id == run_id)
            .values(
                model_usage_status=aggregate_status.value,
                prompt_tokens=aggregate(run_row.prompt_tokens, prompt_tokens),
                completion_tokens=aggregate(run_row.completion_tokens, completion_tokens),
                total_tokens=aggregate(run_row.total_tokens, total_tokens),
                prompt_cache_hit_tokens=aggregate(
                    run_row.prompt_cache_hit_tokens, prompt_cache_hit_tokens
                ),
                prompt_cache_miss_tokens=aggregate(
                    run_row.prompt_cache_miss_tokens, prompt_cache_miss_tokens
                ),
                reasoning_tokens=aggregate(run_row.reasoning_tokens, reasoning_tokens),
                updated_at=now,
            )
        )
        return observed


def _run_values(run: AIRun) -> dict[str, object]:
    values = run.model_dump(mode="python")
    values["id"] = values.pop("run_id")
    values["brief"] = run.brief
    values["run_type"] = run.run_type.value
    values["edit_request"] = run.edit_request
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
        run_type=AIRunType(row.run_type),
        brief=row.brief,
        edit_request=row.edit_request,
        status=AIRunStatus(row.status),
        version=row.version,
        idempotency_key=row.idempotency_key,
        approval_assertion_hash=row.approval_assertion_hash,
        pending_plan_id=row.pending_plan_id,
        pending_plan_content_hash=row.pending_plan_content_hash,
        pending_interrupt_ref=row.pending_interrupt_ref,
        pending_preview_id=row.pending_preview_id,
        materialized_revision_id=row.materialized_revision_id,
        submitted_model_requests=row.submitted_model_requests,
        max_model_requests=row.max_model_requests,
        max_total_tokens=row.max_total_tokens,
        model_usage_status=ModelUsageStatus(row.model_usage_status),
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        prompt_cache_hit_tokens=row.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=row.prompt_cache_miss_tokens,
        reasoning_tokens=row.reasoning_tokens,
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
        "hash_version": plan.hash_version,
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

    try:
        parsed_plan = CompositionPlan.model_validate_json(
            json.dumps(row.plan, allow_nan=False), strict=True
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise ApplicationError(
            "PLAN_INTEGRITY_ERROR", "stored CompositionPlan schema is invalid"
        ) from exc
    hash_version = cast(PlanHashVersion, row.hash_version)
    expected_hash = composition_plan_content_hash(parsed_plan, hash_version=hash_version)
    if row.content_hash != expected_hash:
        raise ApplicationError(
            "PLAN_HASH_MISMATCH",
            f"stored CompositionPlan hash does not match {hash_version}",
        )
    return PersistedCompositionPlan(
        plan_id=row.id,
        run_id=row.run_id,
        plan=parsed_plan,
        content_hash=row.content_hash,
        hash_version=hash_version,
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
        plan.hash_version,
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
        "usage_status": reservation.usage_status.value if reservation.usage_status else None,
        "prompt_tokens": reservation.prompt_tokens,
        "completion_tokens": reservation.completion_tokens,
        "total_tokens": reservation.total_tokens,
        "prompt_cache_hit_tokens": reservation.prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": reservation.prompt_cache_miss_tokens,
        "reasoning_tokens": reservation.reasoning_tokens,
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
        usage_status=ModelUsageStatus(row.usage_status) if row.usage_status else None,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        prompt_cache_hit_tokens=row.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=row.prompt_cache_miss_tokens,
        reasoning_tokens=row.reasoning_tokens,
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

    if row.run_type == AIRunType.EDIT.value:
        return request_hash(
            {
                "schema": "ai-run.create-edit.v1",
                "project_id": str(row.project_id),
                "branch_id": str(row.branch_id),
                "base_revision_id": str(row.base_revision_id),
                "thread_id": row.thread_id,
                "edit_request": row.edit_request,
                "max_model_requests": row.max_model_requests,
                "max_total_tokens": row.max_total_tokens,
            }
        )
    return request_hash(
        {
            "schema": "ai-run.create.v1",
            "project_id": str(row.project_id),
            "branch_id": str(row.branch_id),
            "base_revision_id": str(row.base_revision_id),
            "thread_id": row.thread_id,
            "brief": row.brief,
            "max_model_requests": row.max_model_requests,
            "max_total_tokens": row.max_total_tokens,
            "graph_topology_version": row.graph_topology_version,
            "state_schema_version": row.state_schema_version,
        }
    )
