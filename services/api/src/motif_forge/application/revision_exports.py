"""Finite, explicit exports of authoritative immutable Revisions; no model calls."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.application.errors import ApplicationError
from motif_forge.application.media_jobs import CancelMediaJob, CancelMediaJobRequest
from motif_forge.application.ports import MediaJobUnitOfWorkFactory
from motif_forge.domain.export_plan import CompleteExportCursorV2, plan_export
from motif_forge.domain.ir import DomainModel


class RevisionExportRequest(DomainModel):
    project_id: UUID
    revision_id: UUID
    request_id: UUID
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    include_mp3: bool = True
    include_all_stems: bool = False
    stem_track_ids: tuple[UUID, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.include_all_stems and self.stem_track_ids:
            raise ValueError("EXPORT_STEM_SELECTION_AMBIGUOUS")
        if len(set(self.stem_track_ids)) != len(self.stem_track_ids):
            raise ValueError("EXPORT_TRACK_IDS_NOT_CANONICAL")
        return self


class PrepareRevisionExport:
    def __init__(self, uow_factory: MediaJobUnitOfWorkFactory) -> None:
        self._uow = uow_factory

    async def __call__(
        self, request: RevisionExportRequest, *, thread_id: str
    ) -> CompleteExportCursorV2:
        async with self._uow() as transaction:
            revision = await transaction.get_revision(request.revision_id)
        if revision is None or revision.project_id != request.project_id:
            raise ApplicationError(
                "REVISION_NOT_FOUND", "the revision does not belong to the project"
            )
        stems = (
            tuple(t.track_id for t in revision.arrangement_ir.tracks)
            if request.include_all_stems
            else request.stem_track_ids
        )
        try:
            plan = plan_export(
                revision,
                seed=request.seed,
                include_mp3=request.include_mp3,
                stem_track_ids=stems,
                request_id=request.request_id,
            )
        except ValueError as exc:
            raise ApplicationError("EXPORT_REQUEST_INVALID", str(exc)) from exc
        fingerprint = hashlib.sha256(
            json.dumps(
                request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        async with self._uow() as transaction:
            accepted = await transaction.pin_export_request(
                request_id=request.request_id, request_hash=fingerprint, now=datetime.now(UTC)
            )
        if not accepted:
            raise ApplicationError(
                "IDEMPOTENCY_KEY_REUSED", "the export key was used with a different request"
            )
        return CompleteExportCursorV2(
            plan=plan, plan_hash=plan.content_hash, thread_id=thread_id, run_type="parent.export.v1"
        )


class CancelRevisionExport:
    def __init__(self, uow_factory: MediaJobUnitOfWorkFactory) -> None:
        self._uow = uow_factory

    async def __call__(self, *, project_id: UUID, run_id: UUID, thread_id: str) -> None:
        # Commit the Run intent before locking its Job; followups cannot revive it.
        async with self._uow() as transaction:
            pending = await transaction.cancel_revision_export_run(
                project_id=project_id, run_id=run_id, thread_id=thread_id, now=datetime.now(UTC)
            )
        if pending is None:
            raise ApplicationError(
                "EXPORT_RUN_NOT_FOUND", "the export Run does not belong to this request"
            )
        await CancelMediaJob(self._uow)(
            CancelMediaJobRequest(job_id=pending, actor_id="export-user")
        )
