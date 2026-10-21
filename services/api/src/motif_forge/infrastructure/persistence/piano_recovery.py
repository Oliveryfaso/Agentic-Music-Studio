"""Bounded read-only identity projections for piano recovery discovery."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from motif_forge.application.piano_recovery import PianoRecoverySource
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import (
    AIRunRow,
    IdempotencyRow,
    MediaJobRow,
    MediaRunRow,
    PreviewCandidateRow,
)


class PostgresPianoRecoveryStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_sources(
        self, *, project_id: UUID, branch_id: UUID, now: datetime, limit: int
    ) -> tuple[PianoRecoverySource, ...]:
        if not 1 <= limit <= 11:
            raise ValueError("piano recovery limit must be between 1 and 11")

        thread_id = func.coalesce(MediaRunRow.thread_id, AIRunRow.thread_id)
        piano_request = func.jsonb_typeof(AIRunRow.edit_request["piano_request"]) == "object"
        previews = (
            select(
                thread_id.label("thread_id"),
                PreviewCandidateRow.branch_id,
                PreviewCandidateRow.base_revision_id,
                PreviewCandidateRow.created_at,
                PreviewCandidateRow.id.label("preview_id"),
                PreviewCandidateRow.candidate_content_hash,
                PreviewCandidateRow.expires_at,
            )
            .select_from(PreviewCandidateRow)
            .outerjoin(
                IdempotencyRow,
                and_(
                    IdempotencyRow.resource_id == PreviewCandidateRow.id,
                    IdempotencyRow.operation == "preview.create-from-commands.v1",
                    IdempotencyRow.idempotency_key.like("piano-preview:%"),
                ),
            )
            .outerjoin(
                MediaJobRow,
                and_(
                    MediaJobRow.project_id == PreviewCandidateRow.project_id,
                    or_(
                        MediaJobRow.idempotency_key == IdempotencyRow.idempotency_key + ":baseline",
                        MediaJobRow.idempotency_key == IdempotencyRow.idempotency_key + ":piano",
                    ),
                ),
            )
            .outerjoin(
                MediaRunRow,
                and_(
                    MediaRunRow.id == MediaJobRow.run_id,
                    MediaRunRow.project_id == PreviewCandidateRow.project_id,
                    MediaRunRow.run_type == "parent.piano_preview.v1",
                ),
            )
            .outerjoin(
                AIRunRow,
                and_(
                    AIRunRow.id == PreviewCandidateRow.source_run_id,
                    AIRunRow.project_id == PreviewCandidateRow.project_id,
                    AIRunRow.branch_id == PreviewCandidateRow.branch_id,
                    AIRunRow.base_revision_id == PreviewCandidateRow.base_revision_id,
                    AIRunRow.run_type == "edit",
                    piano_request,
                ),
            )
            .where(
                PreviewCandidateRow.project_id == project_id,
                PreviewCandidateRow.branch_id == branch_id,
                PreviewCandidateRow.status == "pending",
                PreviewCandidateRow.expires_at > now,
                or_(IdempotencyRow.id.is_not(None), AIRunRow.id.is_not(None)),
            )
            # Both render steps share a thread; DISTINCT precedes the bounded limit.
            .distinct()
            .order_by(
                PreviewCandidateRow.created_at.desc(),
                thread_id.desc().nulls_last(),
                PreviewCandidateRow.id.desc(),
            )
            .limit(limit)
        )
        early = (
            select(
                AIRunRow.thread_id,
                AIRunRow.branch_id,
                AIRunRow.base_revision_id,
                AIRunRow.created_at,
                AIRunRow.status.label("early_phase"),
            )
            .where(
                AIRunRow.project_id == project_id,
                AIRunRow.branch_id == branch_id,
                AIRunRow.run_type == "edit",
                AIRunRow.status.in_(("queued", "planning")),
                piano_request,
                # Any materialized Preview owns lifecycle, including expired/terminal rows.
                ~select(PreviewCandidateRow.id)
                .where(PreviewCandidateRow.source_run_id == AIRunRow.id)
                .exists(),
            )
            .order_by(AIRunRow.created_at.desc(), AIRunRow.thread_id.desc(), AIRunRow.id.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            preview_rows = (await session.execute(previews)).mappings().all()
            early_rows = (await session.execute(early)).mappings().all()

        sources = [PianoRecoverySource.model_validate(row) for row in (*preview_rows, *early_rows)]
        sources.sort(
            key=lambda item: (item.created_at, item.thread_id or "", str(item.preview_id or "")),
            reverse=True,
        )
        found: list[PianoRecoverySource] = []
        seen: set[tuple[str, str]] = set()
        for source in sources:
            # Distinct orphan Previews must not collapse into one missing-thread result.
            identity = (
                ("thread", source.thread_id)
                if source.thread_id is not None
                else ("preview", str(source.preview_id))
            )
            if identity not in seen:
                seen.add(identity)
                found.append(source)
                if len(found) == limit:
                    break
        return tuple(found)
