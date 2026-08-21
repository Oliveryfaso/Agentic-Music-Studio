"""Sequential candidate audition Job orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field

from motif_forge.application.errors import ApplicationError
from motif_forge.application.media_jobs import EnqueueMediaJob, EnqueueMediaJobRequest
from motif_forge.application.ports import MediaJobUnitOfWorkFactory
from motif_forge.application.rendering import build_candidate_preview_payload
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    JobStatus,
    MediaJobType,
    MediaQualityProfile,
    RenderScope,
)


class EnqueueCandidatePreviewRequest(DomainModel):
    project_id: UUID
    candidate_snapshot_id: UUID
    expected_candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    thread_id: str = Field(min_length=1, max_length=160)
    seed: int = Field(ge=0, le=2**31 - 1)
    idempotency_key: str = Field(min_length=8, max_length=160)


class CandidatePreviewCursor(DomainModel):
    schema_version: str = "candidate-preview-cursor.v1"
    project_id: UUID
    candidate_snapshot_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_run_id: UUID
    job_id: UUID
    preview_artifact_id: UUID | None = None
    replayed: bool = False


class EnqueueCandidatePreview:
    def __init__(
        self,
        uow_factory: MediaJobUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._enqueue = EnqueueMediaJob(uow_factory, clock=clock)

    async def __call__(self, request: EnqueueCandidatePreviewRequest) -> CandidatePreviewCursor:
        async with self._uow_factory() as transaction:
            snapshot = await transaction.get_candidate_snapshot(request.candidate_snapshot_id)
        if (
            snapshot is None
            or snapshot.project_id != request.project_id
            or snapshot.candidate_content_hash != request.expected_candidate_content_hash
        ):
            raise ApplicationError(
                "CANDIDATE_PREVIEW_LINEAGE_MISMATCH",
                "candidate preview request does not match the immutable Snapshot",
            )
        payload = build_candidate_preview_payload(snapshot, seed=request.seed)
        result = await self._enqueue(
            EnqueueMediaJobRequest(
                project_id=request.project_id,
                thread_id=request.thread_id,
                run_type="parent.candidate_preview.v1",
                job_type=MediaJobType.RENDER_PREVIEW,
                input_payload=payload.model_dump(mode="json"),
                output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
                idempotency_key=request.idempotency_key,
                max_attempts=2,
                deadline_seconds=300,
            )
        )
        return CandidatePreviewCursor(
            project_id=request.project_id,
            candidate_snapshot_id=request.candidate_snapshot_id,
            candidate_content_hash=request.expected_candidate_content_hash,
            media_run_id=result.run_id,
            job_id=result.job_id,
            replayed=result.replayed,
        )


class CollectCandidatePreview:
    def __init__(self, uow_factory: MediaJobUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(
        self, cursor: CandidatePreviewCursor, completed_job_id: UUID
    ) -> CandidatePreviewCursor:
        if completed_job_id != cursor.job_id:
            raise ApplicationError(
                "CANDIDATE_PREVIEW_JOB_MISMATCH", "completion belongs to another Job"
            )
        async with self._uow_factory() as transaction:
            job = await transaction.get_media_job(completed_job_id)
            if (
                job is None
                or job.project_id != cursor.project_id
                or job.run_id != cursor.media_run_id
                or job.job_type is not MediaJobType.RENDER_PREVIEW
                or job.status is not JobStatus.SUCCEEDED
                or job.result_artifact_id is None
            ):
                raise ApplicationError(
                    "CANDIDATE_PREVIEW_NOT_COMPLETE", "candidate preview Job is not complete"
                )
            artifact = await transaction.get_audio_artifact(job.result_artifact_id)
        if (
            artifact is None
            or artifact.project_id != cursor.project_id
            or artifact.source_job_id != cursor.job_id
            or artifact.candidate_snapshot_id != cursor.candidate_snapshot_id
            or artifact.arrangement_hash != cursor.candidate_content_hash
            or artifact.quality_profile is not MediaQualityProfile.CANDIDATE_PREVIEW_V1
            or artifact.render_scope is not RenderScope.MASTER
            or artifact.availability is not ArtifactAvailability.AVAILABLE
        ):
            raise ApplicationError(
                "CANDIDATE_PREVIEW_LINEAGE_MISMATCH",
                "candidate preview Artifact does not match its Snapshot and Job",
            )
        return cursor.model_copy(update={"preview_artifact_id": artifact.artifact_id})
