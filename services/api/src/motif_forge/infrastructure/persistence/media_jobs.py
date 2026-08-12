"""PostgreSQL transaction adapter for durable media Jobs and Worker events."""

from __future__ import annotations

import json
from datetime import datetime
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    ArtifactValidationStatus,
    AudioArtifact,
    FeatureArtifact,
    FeatureProfile,
    ImportedAudioAnalysis,
    JobStatus,
    MediaJob,
    MediaJobType,
    MediaQualityProfile,
    MediaRun,
    RebuildRecipe,
    RunStatus,
    WorkerEvent,
)
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    FeatureArtifactRow,
    InboxReceiptRow,
    JobEventRow,
    MediaJobRow,
    MediaRunRow,
    OutboxEventRow,
    RunEventRow,
)


class PostgresMediaJobUnitOfWork:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresMediaJobTransaction:
        return PostgresMediaJobTransaction(self._session_factory())


class PostgresMediaJobTransaction:
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

    async def find_media_job_by_key(
        self, *, project_id: UUID, job_type: str, idempotency_key: str
    ) -> MediaJob | None:
        row = (
            await self._session.execute(
                select(MediaJobRow).where(
                    MediaJobRow.project_id == project_id,
                    MediaJobRow.job_type == job_type,
                    MediaJobRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _job_from_row(row)

    async def get_media_job(self, job_id: UUID, *, for_update: bool = False) -> MediaJob | None:
        statement = select(MediaJobRow).where(MediaJobRow.id == job_id)
        if for_update:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return None if row is None else _job_from_row(row)

    async def get_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None:
        row = (
            await self._session.execute(
                select(AudioArtifactRow).where(AudioArtifactRow.id == artifact_id)
            )
        ).scalar_one_or_none()
        return None if row is None else _artifact_from_row(row)

    async def get_feature_artifact(self, artifact_id: UUID) -> FeatureArtifact | None:
        row = (
            await self._session.execute(
                select(FeatureArtifactRow).where(FeatureArtifactRow.id == artifact_id)
            )
        ).scalar_one_or_none()
        return None if row is None else _feature_from_row(row)

    async def get_feature_artifact_for_source(
        self, source_artifact_id: UUID, feature_profile: FeatureProfile
    ) -> FeatureArtifact | None:
        row = (
            await self._session.execute(
                select(FeatureArtifactRow).where(
                    FeatureArtifactRow.source_audio_artifact_id == source_artifact_id,
                    FeatureArtifactRow.feature_profile == feature_profile.value,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _feature_from_row(row)

    async def list_feature_artifacts_for_source(
        self, source_artifact_id: UUID
    ) -> tuple[FeatureArtifact, ...]:
        rows = (
            await self._session.execute(
                select(FeatureArtifactRow)
                .where(FeatureArtifactRow.source_audio_artifact_id == source_artifact_id)
                .order_by(FeatureArtifactRow.feature_profile)
            )
        ).scalars()
        return tuple(_feature_from_row(row) for row in rows)

    async def lock_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None:
        row = (
            await self._session.execute(
                select(AudioArtifactRow).where(AudioArtifactRow.id == artifact_id).with_for_update()
            )
        ).scalar_one_or_none()
        return None if row is None else _artifact_from_row(row)

    async def lock_feature_artifact(self, artifact_id: UUID) -> FeatureArtifact | None:
        row = (
            await self._session.execute(
                select(FeatureArtifactRow)
                .where(FeatureArtifactRow.id == artifact_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return None if row is None else _feature_from_row(row)

    async def claim_media_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> MediaJob | None:
        row = (
            await self._session.execute(
                select(MediaJobRow).where(MediaJobRow.id == job_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        terminal = {
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED_TERMINAL.value,
            JobStatus.CANCELLED.value,
        }
        active_lease = (
            row.status == JobStatus.RUNNING.value
            and row.lease_expires_at is not None
            and row.lease_expires_at > now
        )
        if (
            row.status in terminal
            or active_lease
            or row.deadline_at <= now
            or row.attempts >= row.max_attempts
        ):
            return None
        row.status = JobStatus.RUNNING.value
        row.attempts += 1
        row.lease_owner = worker_id
        row.lease_expires_at = lease_expires_at
        row.heartbeat_at = now
        row.progress_percent = 1
        row.error_code = None
        row.updated_at = now
        await self._session.execute(
            update(MediaRunRow)
            .where(MediaRunRow.id == row.run_id)
            .values(status=RunStatus.RUNNING.value, updated_at=now)
        )
        await self._session.execute(
            insert(JobEventRow).values(
                id=uuid4(),
                job_id=row.id,
                event_type="job.started",
                external_event_id=None,
                payload={"attempt": row.attempts, "worker_id": worker_id},
                created_at=now,
            )
        )
        return _job_from_row(row)

    async def heartbeat_media_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        progress_percent: int,
    ) -> bool:
        result = await self._session.execute(
            update(MediaJobRow)
            .where(
                MediaJobRow.id == job_id,
                MediaJobRow.status == JobStatus.RUNNING.value,
                MediaJobRow.lease_owner == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                progress_percent=progress_percent,
                updated_at=now,
            )
        )
        return bool(cast(CursorResult[Any], result).rowcount)

    async def has_inbox_receipt(self, *, consumer: str, event_id: str) -> bool:
        row = (
            await self._session.execute(
                select(InboxReceiptRow.id).where(
                    InboxReceiptRow.consumer == consumer,
                    InboxReceiptRow.event_id == event_id,
                )
            )
        ).one_or_none()
        return row is not None

    async def insert_media_run_job(
        self,
        *,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None:
        await self._session.execute(insert(MediaRunRow).values(**_run_values(run)))
        await self._session.execute(insert(MediaJobRow).values(**_job_values(job)))
        await self._session.execute(
            insert(RunEventRow).values(
                id=run_event_id,
                run_id=run.run_id,
                event_type="run.waiting_worker",
                payload={"job_id": str(job.job_id), "job_type": job.job_type.value},
                created_at=run.created_at,
            )
        )
        await self._session.execute(
            insert(JobEventRow).values(
                id=job_event_id,
                job_id=job.job_id,
                event_type="job.queued",
                external_event_id=None,
                payload={
                    "quality_profile": (
                        job.output_quality_profile.value
                        if job.output_quality_profile is not None
                        else None
                    ),
                    "feature_profile": (
                        job.output_feature_profile.value
                        if job.output_feature_profile is not None
                        else None
                    ),
                },
                created_at=job.created_at,
            )
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="job",
                aggregate_id=job.job_id,
                topic="media.job.dispatch.requested",
                dedupe_key=f"dispatch:{job.job_id}",
                payload={"job_id": str(job.job_id), "job_type": job.job_type.value},
                status="pending",
                attempts=0,
                available_at=job.created_at,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=None,
                published_at=None,
                created_at=job.created_at,
            )
        )

    async def insert_rehydration_run_job(
        self,
        *,
        target_artifact_id: UUID,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None:
        if job.job_type is not MediaJobType.REHYDRATE:
            raise RuntimeError("rehydration transaction requires a rehydrate Job")
        changed = await self._session.execute(
            update(AudioArtifactRow)
            .where(
                AudioArtifactRow.id == target_artifact_id,
                AudioArtifactRow.project_id == job.project_id,
                AudioArtifactRow.availability == ArtifactAvailability.EVICTED.value,
                AudioArtifactRow.lifecycle_class == ArtifactLifecycle.REBUILDABLE.value,
            )
            .values(
                availability=ArtifactAvailability.REHYDRATING.value,
                rehydration_job_id=job.job_id,
            )
        )
        if not cast(CursorResult[Any], changed).rowcount:
            raise RuntimeError("rehydration target lost its evicted precondition")
        await self.insert_media_run_job(
            run=run,
            job=job,
            run_event_id=run_event_id,
            job_event_id=job_event_id,
            outbox_event_id=outbox_event_id,
        )

    async def insert_feature_rehydration_run_job(
        self,
        *,
        target_artifact_id: UUID,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None:
        if job.job_type is not MediaJobType.REHYDRATE_FEATURE:
            raise RuntimeError("Feature rehydration requires a rehydrate_feature Job")
        changed = await self._session.execute(
            update(FeatureArtifactRow)
            .where(
                FeatureArtifactRow.id == target_artifact_id,
                FeatureArtifactRow.project_id == job.project_id,
                FeatureArtifactRow.availability == ArtifactAvailability.EVICTED.value,
                FeatureArtifactRow.lifecycle_class == ArtifactLifecycle.REBUILDABLE.value,
            )
            .values(
                availability=ArtifactAvailability.REHYDRATING.value,
                rehydration_job_id=job.job_id,
            )
        )
        if not cast(CursorResult[Any], changed).rowcount:
            raise RuntimeError("Feature rehydration target lost its evicted precondition")
        await self.insert_media_run_job(
            run=run,
            job=job,
            run_event_id=run_event_id,
            job_event_id=job_event_id,
            outbox_event_id=outbox_event_id,
        )

    async def append_media_job_to_run(
        self,
        *,
        expected_thread_id: str,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> bool:
        run = (
            await self._session.execute(
                select(MediaRunRow)
                .where(
                    MediaRunRow.id == job.run_id,
                    MediaRunRow.project_id == job.project_id,
                    MediaRunRow.thread_id == expected_thread_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            return False
        await self._session.execute(insert(MediaJobRow).values(**_job_values(job)))
        run.status = RunStatus.WAITING_WORKER.value
        run.waiting_for_job_id = job.job_id
        run.updated_at = job.created_at
        await self._session.execute(
            insert(RunEventRow).values(
                id=run_event_id,
                run_id=run.id,
                event_type="run.waiting_worker",
                payload={"job_id": str(job.job_id), "job_type": job.job_type.value},
                created_at=job.created_at,
            )
        )
        await self._session.execute(
            insert(JobEventRow).values(
                id=job_event_id,
                job_id=job.job_id,
                event_type="job.queued",
                external_event_id=None,
                payload={
                    "quality_profile": (
                        job.output_quality_profile.value
                        if job.output_quality_profile is not None
                        else None
                    ),
                    "feature_profile": (
                        job.output_feature_profile.value
                        if job.output_feature_profile is not None
                        else None
                    ),
                },
                created_at=job.created_at,
            )
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="job",
                aggregate_id=job.job_id,
                topic="media.job.dispatch.requested",
                dedupe_key=f"dispatch:{job.job_id}",
                payload={"job_id": str(job.job_id), "job_type": job.job_type.value},
                status="pending",
                attempts=0,
                available_at=job.created_at,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=None,
                published_at=None,
                created_at=job.created_at,
            )
        )
        return True

    async def apply_worker_event(
        self,
        *,
        event: WorkerEvent,
        updated_job: MediaJob,
        run_status: RunStatus,
        artifact: AudioArtifact | FeatureArtifact | None,
        feature_artifacts: tuple[FeatureArtifact, ...],
        validated_source_artifact: AudioArtifact | None,
        consumer: str,
        inbox_receipt_id: UUID,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
        outbox_topic: str,
    ) -> AudioArtifact | FeatureArtifact | None:
        if validated_source_artifact is not None:
            await self._update_validated_source_artifact(validated_source_artifact)
        if isinstance(artifact, FeatureArtifact):
            persisted_artifact: AudioArtifact | FeatureArtifact | None = (
                await self._register_or_reuse_feature(artifact)
            )
        else:
            persisted_artifact = await self._register_or_reuse_artifact(artifact)
        for feature in feature_artifacts:
            await self._register_or_reuse_feature(feature)
        if updated_job.job_type in {
            MediaJobType.REHYDRATE,
            MediaJobType.REHYDRATE_FEATURE,
        } and updated_job.status is JobStatus.FAILED_TERMINAL:
            await self._release_failed_rehydration(updated_job)
        result_artifact_id = (
            persisted_artifact.artifact_id if persisted_artifact is not None else None
        )
        await self._session.execute(
            update(MediaJobRow)
            .where(MediaJobRow.id == updated_job.job_id)
            .values(
                status=updated_job.status.value,
                result_artifact_id=result_artifact_id,
                error_code=updated_job.error_code,
                attempts=updated_job.attempts,
                heartbeat_at=event.occurred_at,
                lease_owner=None,
                lease_expires_at=None,
                progress_percent=(100 if updated_job.status is JobStatus.SUCCEEDED else 0),
                updated_at=updated_job.updated_at,
            )
        )
        await self._session.execute(
            update(MediaRunRow)
            .where(MediaRunRow.id == updated_job.run_id)
            .values(status=run_status.value, updated_at=event.occurred_at)
        )
        await self._session.execute(
            insert(InboxReceiptRow).values(
                id=inbox_receipt_id,
                consumer=consumer,
                event_id=event.event_id,
                processed_at=event.occurred_at,
            )
        )
        run_identity = (
            await self._session.execute(
                select(MediaRunRow.thread_id, MediaRunRow.run_type).where(
                    MediaRunRow.id == updated_job.run_id
                )
            )
        ).one_or_none()
        if run_identity is None:
            raise RuntimeError("media Run disappeared while applying Worker event")
        thread_id, run_type = run_identity
        payload = {
            "schema_version": (
                "worker-resume.v1"
                if outbox_topic == "graph.resume.requested"
                else "media-job-retry.v1"
            ),
            "run_id": str(updated_job.run_id),
            "thread_id": thread_id,
            "run_type": run_type,
            "resume_event_id": event.event_id,
            "job_id": str(updated_job.job_id),
            "status": updated_job.status.value,
            "artifact_id": str(result_artifact_id) if result_artifact_id else None,
            "error_code": updated_job.error_code,
        }
        await self._session.execute(
            insert(JobEventRow).values(
                id=job_event_id,
                job_id=updated_job.job_id,
                event_type=event.event_type,
                external_event_id=event.event_id,
                payload=payload,
                created_at=event.occurred_at,
            )
        )
        await self._session.execute(
            insert(RunEventRow).values(
                id=run_event_id,
                run_id=updated_job.run_id,
                event_type=(
                    "run.worker_completed"
                    if updated_job.status is JobStatus.SUCCEEDED
                    else "run.worker_failed"
                ),
                payload=payload,
                created_at=event.occurred_at,
            )
        )
        await self._session.execute(
            insert(OutboxEventRow).values(
                id=outbox_event_id,
                aggregate_type="run",
                aggregate_id=updated_job.run_id,
                topic=outbox_topic,
                dedupe_key=f"{outbox_topic}:{event.event_id}",
                payload=payload,
                status="pending",
                attempts=0,
                available_at=event.occurred_at,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=None,
                published_at=None,
                created_at=event.occurred_at,
            )
        )
        return persisted_artifact

    async def _update_validated_source_artifact(self, artifact: AudioArtifact) -> None:
        result = await self._session.execute(
            update(AudioArtifactRow)
            .where(
                AudioArtifactRow.id == artifact.artifact_id,
                AudioArtifactRow.project_id == artifact.project_id,
                AudioArtifactRow.content_hash == artifact.content_hash,
                AudioArtifactRow.validation_status == ArtifactValidationStatus.QUARANTINED.value,
            )
            .values(
                codec=artifact.codec,
                sample_rate_hz=artifact.sample_rate_hz,
                channels=artifact.channels,
                duration_milliseconds=round((artifact.duration_seconds or 0) * 1000),
                bitrate_kbps=artifact.bitrate_kbps,
                bit_depth=artifact.bit_depth,
                validation_status=ArtifactValidationStatus.VALIDATED.value,
            )
        )
        if not cast(CursorResult[Any], result).rowcount:
            raise RuntimeError("source Artifact validation update lost its quarantine precondition")

    async def _register_or_reuse_artifact(
        self, artifact: AudioArtifact | None
    ) -> AudioArtifact | None:
        if artifact is None:
            return None
        existing = (
            await self._session.execute(
                select(AudioArtifactRow).where(
                    AudioArtifactRow.project_id == artifact.project_id,
                    AudioArtifactRow.content_hash == artifact.content_hash,
                    AudioArtifactRow.quality_profile == artifact.quality_profile.value,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if artifact.artifact_id == existing.id and artifact.source_job_id is not None:
                if (
                    existing.availability != ArtifactAvailability.REHYDRATING.value
                    or existing.rehydration_job_id != artifact.source_job_id
                    or existing.recipe_hash != artifact.recipe_hash
                ):
                    raise RuntimeError("rehydrated Artifact lost its locked lifecycle contract")
                existing.availability = ArtifactAvailability.AVAILABLE.value
                existing.evicted_at = None
                existing.rehydration_job_id = None
                existing.last_accessed_at = artifact.last_accessed_at
                existing.byte_size = artifact.byte_size
                existing.storage_key = artifact.storage_key
            return _artifact_from_row(existing)
        await self._session.execute(insert(AudioArtifactRow).values(**_artifact_values(artifact)))
        return artifact

    async def _register_or_reuse_feature(self, artifact: FeatureArtifact) -> FeatureArtifact:
        existing = (
            await self._session.execute(
                select(FeatureArtifactRow).where(
                    FeatureArtifactRow.source_audio_artifact_id
                    == artifact.source_audio_artifact_id,
                    FeatureArtifactRow.source_audio_content_hash
                    == artifact.source_audio_content_hash,
                    FeatureArtifactRow.feature_profile == artifact.feature_profile.value,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if artifact.artifact_id == existing.id:
                if (
                    existing.availability != ArtifactAvailability.REHYDRATING.value
                    or existing.rehydration_job_id != artifact.source_job_id
                    or existing.recipe_hash != artifact.recipe_hash
                ):
                    raise RuntimeError("rehydrated Feature lost its locked lifecycle contract")
                existing.availability = ArtifactAvailability.AVAILABLE.value
                existing.evicted_at = None
                existing.rehydration_job_id = None
                existing.last_accessed_at = artifact.last_accessed_at
                existing.byte_size = artifact.byte_size
                existing.storage_key = artifact.storage_key
            return _feature_from_row(existing)
        await self._session.execute(
            insert(FeatureArtifactRow).values(**_feature_values(artifact))
        )
        return artifact

    async def _release_failed_rehydration(self, job: MediaJob) -> None:
        try:
            target_artifact_id = UUID(str(job.input_payload["target_artifact_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("rehydration Job lost its target Artifact identity") from exc
        availability = (
            ArtifactAvailability.MISSING.value
            if job.error_code
            in {
                "SOURCE_ARTIFACT_UNAVAILABLE",
                "ARTIFACT_REHYDRATION_CHECKSUM_MISMATCH",
                "ARTIFACT_REHYDRATION_RECIPE_MISMATCH",
            }
            else ArtifactAvailability.EVICTED.value
        )
        table = (
            FeatureArtifactRow
            if job.job_type is MediaJobType.REHYDRATE_FEATURE
            else AudioArtifactRow
        )
        await self._session.execute(
            update(table)
            .where(
                table.id == target_artifact_id,
                table.availability == ArtifactAvailability.REHYDRATING.value,
                table.rehydration_job_id == job.job_id,
            )
            .values(availability=availability, rehydration_job_id=None)
        )


def _run_values(run: MediaRun) -> dict[str, object]:
    return {
        "id": run.run_id,
        "project_id": run.project_id,
        "thread_id": run.thread_id,
        "run_type": run.run_type,
        "status": run.status.value,
        "waiting_for_job_id": run.waiting_for_job_id,
        "schema_version": run.schema_version,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _job_values(job: MediaJob) -> dict[str, object]:
    return {
        "id": job.job_id,
        "run_id": job.run_id,
        "project_id": job.project_id,
        "job_type": job.job_type.value,
        "status": job.status.value,
        "idempotency_key": job.idempotency_key,
        "request_hash": job.request_hash,
        "input_payload": job.input_payload,
        "output_quality_profile": (
            job.output_quality_profile.value if job.output_quality_profile is not None else None
        ),
        "output_feature_profile": (
            job.output_feature_profile.value if job.output_feature_profile is not None else None
        ),
        "result_artifact_id": job.result_artifact_id,
        "error_code": job.error_code,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "deadline_at": job.deadline_at,
        "heartbeat_at": job.heartbeat_at,
        "lease_owner": job.lease_owner,
        "lease_expires_at": job.lease_expires_at,
        "progress_percent": job.progress_percent,
        "schema_version": job.schema_version,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _artifact_values(artifact: AudioArtifact) -> dict[str, object]:
    return {
        "id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "source_job_id": artifact.source_job_id,
        "source_upload_id": artifact.source_upload_id,
        "content_hash": artifact.content_hash,
        "byte_size": artifact.byte_size,
        "storage_key": artifact.storage_key,
        "media_role": artifact.media_role,
        "quality_profile": artifact.quality_profile.value,
        "container": artifact.container,
        "codec": artifact.codec,
        "sample_rate_hz": artifact.sample_rate_hz,
        "channels": artifact.channels,
        "duration_milliseconds": (
            round(artifact.duration_seconds * 1000)
            if artifact.duration_seconds is not None
            else None
        ),
        "bitrate_kbps": artifact.bitrate_kbps,
        "bit_depth": artifact.bit_depth,
        "encoder": artifact.encoder,
        "encoder_version": artifact.encoder_version,
        "lifecycle_class": artifact.lifecycle_class.value,
        "availability": artifact.availability.value,
        "validation_status": artifact.validation_status.value,
        "recipe_hash": artifact.recipe_hash,
        "rebuild_recipe": (
            artifact.rebuild_recipe.model_dump(mode="json")
            if artifact.rebuild_recipe is not None
            else None
        ),
        "protection_reasons": list(artifact.protection_reasons),
        "analysis": (
            artifact.analysis.model_dump(mode="json") if artifact.analysis is not None else None
        ),
        "schema_version": artifact.schema_version,
        "created_at": artifact.created_at,
        "last_accessed_at": artifact.last_accessed_at,
        "expires_at": artifact.expires_at,
        "evicted_at": artifact.evicted_at,
        "rehydration_job_id": artifact.rehydration_job_id,
    }


def _feature_values(artifact: FeatureArtifact) -> dict[str, object]:
    return {
        "id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "source_job_id": artifact.source_job_id,
        "source_audio_artifact_id": artifact.source_audio_artifact_id,
        "source_audio_content_hash": artifact.source_audio_content_hash,
        "content_hash": artifact.content_hash,
        "byte_size": artifact.byte_size,
        "storage_key": artifact.storage_key,
        "feature_profile": artifact.feature_profile.value,
        "feature_schema_version": artifact.feature_schema_version,
        "content_type": artifact.content_type,
        "lifecycle_class": artifact.lifecycle_class.value,
        "availability": artifact.availability.value,
        "recipe_hash": artifact.recipe_hash,
        "rebuild_recipe": artifact.rebuild_recipe.model_dump(mode="json"),
        "protection_reasons": list(artifact.protection_reasons),
        "last_accessed_at": artifact.last_accessed_at,
        "expires_at": artifact.expires_at,
        "evicted_at": artifact.evicted_at,
        "rehydration_job_id": artifact.rehydration_job_id,
        "schema_version": artifact.schema_version,
        "created_at": artifact.created_at,
    }


def _job_from_row(row: MediaJobRow) -> MediaJob:
    return MediaJob(
        job_id=row.id,
        run_id=row.run_id,
        project_id=row.project_id,
        job_type=MediaJobType(row.job_type),
        status=JobStatus(row.status),
        idempotency_key=row.idempotency_key,
        request_hash=row.request_hash,
        input_payload=row.input_payload,
        output_quality_profile=(
            MediaQualityProfile(row.output_quality_profile)
            if row.output_quality_profile is not None
            else None
        ),
        output_feature_profile=(
            FeatureProfile(row.output_feature_profile)
            if row.output_feature_profile is not None
            else None
        ),
        result_artifact_id=row.result_artifact_id,
        error_code=row.error_code,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        deadline_at=row.deadline_at,
        heartbeat_at=row.heartbeat_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        progress_percent=row.progress_percent,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _artifact_from_row(row: AudioArtifactRow) -> AudioArtifact:
    return AudioArtifact(
        artifact_id=row.id,
        project_id=row.project_id,
        source_job_id=row.source_job_id,
        source_upload_id=row.source_upload_id,
        content_hash=row.content_hash,
        byte_size=row.byte_size,
        storage_key=row.storage_key,
        media_role=row.media_role,
        quality_profile=MediaQualityProfile(row.quality_profile),
        container=row.container,
        codec=row.codec,
        sample_rate_hz=row.sample_rate_hz,
        channels=row.channels,
        duration_seconds=(
            row.duration_milliseconds / 1000 if row.duration_milliseconds is not None else None
        ),
        bitrate_kbps=row.bitrate_kbps,
        bit_depth=row.bit_depth,
        encoder=row.encoder,
        encoder_version=row.encoder_version,
        lifecycle_class=ArtifactLifecycle(row.lifecycle_class),
        availability=ArtifactAvailability(row.availability),
        validation_status=ArtifactValidationStatus(row.validation_status),
        recipe_hash=row.recipe_hash,
        rebuild_recipe=(
            RebuildRecipe.model_validate_json(json.dumps(row.rebuild_recipe), strict=True)
            if row.rebuild_recipe is not None
            else None
        ),
        protection_reasons=tuple(row.protection_reasons),
        analysis=(
            ImportedAudioAnalysis.model_validate(row.analysis) if row.analysis is not None else None
        ),
        created_at=row.created_at,
        last_accessed_at=row.last_accessed_at,
        expires_at=row.expires_at,
        evicted_at=row.evicted_at,
        rehydration_job_id=row.rehydration_job_id,
    )


def _feature_from_row(row: FeatureArtifactRow) -> FeatureArtifact:
    return FeatureArtifact(
        artifact_id=row.id,
        project_id=row.project_id,
        source_job_id=row.source_job_id,
        source_audio_artifact_id=row.source_audio_artifact_id,
        source_audio_content_hash=row.source_audio_content_hash,
        content_hash=row.content_hash,
        byte_size=row.byte_size,
        storage_key=row.storage_key,
        feature_profile=FeatureProfile(row.feature_profile),
        feature_schema_version=row.feature_schema_version,
        content_type="application/json",
        lifecycle_class=ArtifactLifecycle(row.lifecycle_class),
        availability=ArtifactAvailability(row.availability),
        recipe_hash=row.recipe_hash,
        rebuild_recipe=RebuildRecipe.model_validate_json(
            json.dumps(row.rebuild_recipe), strict=True
        ),
        protection_reasons=tuple(row.protection_reasons),
        created_at=row.created_at,
        last_accessed_at=row.last_accessed_at,
        expires_at=row.expires_at,
        evicted_at=row.evicted_at,
        rehydration_job_id=row.rehydration_job_id,
    )
