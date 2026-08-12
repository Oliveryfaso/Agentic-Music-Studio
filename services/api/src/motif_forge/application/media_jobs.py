"""Atomic Job/Outbox creation and idempotent Worker completion."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import (
    ArtifactRehydrationError,
    IdempotencyKeyReusedError,
    MediaJobNotFoundError,
    MediaJobStateConflictError,
)
from motif_forge.application.ports import MediaJobUnitOfWorkFactory
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
    ExportBundleArtifact,
    FeatureArtifact,
    FeatureProfile,
    FeatureRehydrateJobPayload,
    JobStatus,
    MediaJob,
    MediaJobType,
    MediaQualityProfile,
    MediaRun,
    RehydrateJobPayload,
    RunStatus,
    WorkerEvent,
)


class EnqueueMediaJobRequest(DomainModel):
    project_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    run_type: str = Field(min_length=1, max_length=80)
    job_type: MediaJobType
    input_payload: dict[str, object]
    output_quality_profile: MediaQualityProfile | None = None
    output_feature_profile: FeatureProfile | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)
    max_attempts: int = Field(default=3, ge=1, le=5)
    deadline_seconds: int = Field(default=900, ge=30, le=3600)


class EnqueueMediaJobResult(DomainModel):
    run_id: UUID
    job_id: UUID
    status: JobStatus
    replayed: bool = False


class EnqueueFollowupMediaJobRequest(DomainModel):
    run_id: UUID
    project_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    job_type: MediaJobType
    input_payload: dict[str, object]
    output_quality_profile: MediaQualityProfile | None = None
    output_feature_profile: FeatureProfile | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)
    max_attempts: int = Field(default=3, ge=1, le=5)
    deadline_seconds: int = Field(default=900, ge=30, le=3600)


class CancelMediaJobRequest(DomainModel):
    job_id: UUID
    actor_id: str = Field(min_length=1, max_length=160)


class WorkerEventResult(DomainModel):
    run_id: UUID
    job_id: UUID
    status: JobStatus
    artifact_id: UUID | None = None
    replayed: bool = False


class CancelMediaJob:
    """Persist an explicit cancellation that prevents or supersedes Worker completion."""

    def __init__(
        self,
        uow_factory: MediaJobUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def __call__(self, request: CancelMediaJobRequest) -> MediaJob:
        async with self._uow_factory() as transaction:
            job = await transaction.cancel_media_job(
                request.job_id,
                actor_id=request.actor_id,
                now=self._clock(),
            )
            if job is None:
                raise MediaJobNotFoundError
            return job


class StartArtifactRehydrationRequest(DomainModel):
    project_id: UUID
    artifact_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)
    max_attempts: int = Field(default=3, ge=1, le=5)
    deadline_seconds: int = Field(default=900, ge=30, le=3600)


class LoadArtifactRehydration:
    """Read and compile one executable rebuild request without changing lifecycle state."""

    def __init__(self, uow_factory: MediaJobUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(
        self, *, artifact_id: UUID
    ) -> tuple[UUID, RehydrateJobPayload | FeatureRehydrateJobPayload]:
        async with self._uow_factory() as transaction:
            target: AudioArtifact | FeatureArtifact | None = await transaction.get_audio_artifact(
                artifact_id
            )
            if target is None:
                target = await transaction.get_feature_artifact(artifact_id)
            payload = _compile_rehydrate_payload(target, project_id=None)
            assert target is not None
            assert target.rebuild_recipe is not None
            source = await transaction.get_audio_artifact(payload.source_artifact_id)
            expected_hash = target.rebuild_recipe.input_artifacts[0].content_hash
            if (
                source is None
                or source.project_id != target.project_id
                or source.availability is not ArtifactAvailability.AVAILABLE
                or source.content_hash != expected_hash
            ):
                raise ArtifactRehydrationError(
                    "ARTIFACT_REHYDRATION_DEPENDENCY_UNAVAILABLE",
                    "the pinned source Artifact is unavailable or has changed",
                )
            return target.project_id, payload


class EnqueueMediaJob:
    """Create Run, Job, durable events, and publish intent in one transaction."""

    def __init__(
        self,
        uow_factory: MediaJobUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, request: EnqueueMediaJobRequest) -> EnqueueMediaJobResult:
        fingerprint = request_hash(
            {
                "schema": "media-job-enqueue.v1",
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        async with self._uow_factory() as transaction:
            existing = await transaction.find_media_job_by_key(
                project_id=request.project_id,
                job_type=request.job_type,
                idempotency_key=request.idempotency_key,
            )
            if existing is not None:
                if existing.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return EnqueueMediaJobResult(
                    run_id=existing.run_id,
                    job_id=existing.job_id,
                    status=existing.status,
                    replayed=True,
                )

            now = self._clock()
            run_id = self._id_factory()
            job_id = self._id_factory()
            run = MediaRun(
                run_id=run_id,
                project_id=request.project_id,
                thread_id=request.thread_id,
                run_type=request.run_type,
                waiting_for_job_id=job_id,
                created_at=now,
                updated_at=now,
            )
            job = MediaJob(
                job_id=job_id,
                run_id=run_id,
                project_id=request.project_id,
                job_type=request.job_type,
                idempotency_key=request.idempotency_key,
                request_hash=fingerprint,
                input_payload=request.input_payload,
                output_quality_profile=request.output_quality_profile,
                max_attempts=request.max_attempts,
                deadline_at=now + timedelta(seconds=request.deadline_seconds),
                created_at=now,
                updated_at=now,
            )
            await transaction.insert_media_run_job(
                run=run,
                job=job,
                run_event_id=self._id_factory(),
                job_event_id=self._id_factory(),
                outbox_event_id=self._id_factory(),
            )
            return EnqueueMediaJobResult(run_id=run_id, job_id=job_id, status=job.status)


class StartArtifactRehydration:
    """Atomically enqueue one pinned rebuild and move the target to rehydrating."""

    def __init__(
        self,
        uow_factory: MediaJobUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, request: StartArtifactRehydrationRequest) -> EnqueueMediaJobResult:
        async with self._uow_factory() as transaction:
            target: AudioArtifact | FeatureArtifact | None = await transaction.lock_audio_artifact(
                request.artifact_id
            )
            if target is None:
                target = await transaction.lock_feature_artifact(request.artifact_id)
            payload = _compile_rehydrate_payload(target, project_id=request.project_id)
            assert target is not None
            fingerprint = request_hash(
                {
                    "schema": "artifact-rehydrate-enqueue.v1",
                    "project_id": str(request.project_id),
                    "artifact_id": str(request.artifact_id),
                    "payload": payload.model_dump(mode="json"),
                }
            )
            existing = await transaction.find_media_job_by_key(
                project_id=request.project_id,
                job_type=(
                    MediaJobType.REHYDRATE_FEATURE
                    if isinstance(payload, FeatureRehydrateJobPayload)
                    else MediaJobType.REHYDRATE
                ),
                idempotency_key=request.idempotency_key,
            )
            if existing is not None:
                if existing.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                owns_in_progress = (
                    target.availability is ArtifactAvailability.REHYDRATING
                    and target.rehydration_job_id == existing.job_id
                )
                owns_completed = (
                    target.availability is ArtifactAvailability.AVAILABLE
                    and existing.status is JobStatus.SUCCEEDED
                    and existing.result_artifact_id == target.artifact_id
                )
                if not (owns_in_progress or owns_completed):
                    raise ArtifactRehydrationError(
                        "ARTIFACT_REHYDRATION_STATE_CONFLICT",
                        "the idempotent rebuild Job no longer owns the target Artifact",
                    )
                return EnqueueMediaJobResult(
                    run_id=existing.run_id,
                    job_id=existing.job_id,
                    status=existing.status,
                    replayed=True,
                )
            if target.availability is ArtifactAvailability.REHYDRATING:
                raise ArtifactRehydrationError(
                    "ARTIFACT_REHYDRATING",
                    "the target Artifact is already being rebuilt",
                    retryable=True,
                )
            if target.availability is ArtifactAvailability.AVAILABLE:
                raise ArtifactRehydrationError(
                    "ARTIFACT_ALREADY_AVAILABLE", "the target Artifact is already available"
                )
            if target.availability is ArtifactAvailability.MISSING:
                raise ArtifactRehydrationError(
                    "ARTIFACT_MISSING", "the target Artifact cannot be rebuilt automatically"
                )
            assert target.rebuild_recipe is not None
            source = await transaction.get_audio_artifact(payload.source_artifact_id)
            expected_source_hash = target.rebuild_recipe.input_artifacts[0].content_hash
            if (
                source is None
                or source.project_id != request.project_id
                or source.availability is not ArtifactAvailability.AVAILABLE
                or source.content_hash != expected_source_hash
            ):
                raise ArtifactRehydrationError(
                    "ARTIFACT_REHYDRATION_DEPENDENCY_UNAVAILABLE",
                    "the pinned source Artifact is unavailable or has changed",
                )
            now = self._clock()
            run_id = self._id_factory()
            job_id = self._id_factory()
            run = MediaRun(
                run_id=run_id,
                project_id=request.project_id,
                thread_id=request.thread_id,
                run_type="parent.artifact_rehydrate.v1",
                waiting_for_job_id=job_id,
                created_at=now,
                updated_at=now,
            )
            job = MediaJob(
                job_id=job_id,
                run_id=run_id,
                project_id=request.project_id,
                job_type=(
                    MediaJobType.REHYDRATE_FEATURE
                    if isinstance(payload, FeatureRehydrateJobPayload)
                    else MediaJobType.REHYDRATE
                ),
                idempotency_key=request.idempotency_key,
                request_hash=fingerprint,
                input_payload=payload.model_dump(mode="json"),
                output_quality_profile=(
                    target.quality_profile if isinstance(target, AudioArtifact) else None
                ),
                output_feature_profile=(
                    target.feature_profile if isinstance(target, FeatureArtifact) else None
                ),
                max_attempts=request.max_attempts,
                deadline_at=now + timedelta(seconds=request.deadline_seconds),
                created_at=now,
                updated_at=now,
            )
            if isinstance(target, FeatureArtifact):
                await transaction.insert_feature_rehydration_run_job(
                    target_artifact_id=target.artifact_id,
                    run=run,
                    job=job,
                    run_event_id=self._id_factory(),
                    job_event_id=self._id_factory(),
                    outbox_event_id=self._id_factory(),
                )
            else:
                await transaction.insert_rehydration_run_job(
                    target_artifact_id=target.artifact_id,
                    run=run,
                    job=job,
                    run_event_id=self._id_factory(),
                    job_event_id=self._id_factory(),
                    outbox_event_id=self._id_factory(),
                )
            return EnqueueMediaJobResult(run_id=run_id, job_id=job_id, status=job.status)


def _compile_rehydrate_payload(
    target: object, *, project_id: UUID | None
) -> RehydrateJobPayload | FeatureRehydrateJobPayload:
    if not isinstance(target, (AudioArtifact, FeatureArtifact)) or (
        project_id is not None and target.project_id != project_id
    ):
        raise ArtifactRehydrationError("ARTIFACT_NOT_FOUND", "the target Artifact does not exist")
    if target.availability is ArtifactAvailability.MISSING:
        raise ArtifactRehydrationError(
            "ARTIFACT_MISSING", "the target Artifact cannot be rebuilt automatically"
        )
    if (
        target.lifecycle_class is not ArtifactLifecycle.REBUILDABLE
        or target.rebuild_recipe is None
        or target.recipe_hash != target.rebuild_recipe.content_hash
        or target.rebuild_recipe.recipe_kind not in {"time_stretch", "analysis"}
    ):
        raise ArtifactRehydrationError(
            "ARTIFACT_REHYDRATION_UNSUPPORTED",
            "only pinned time-stretch and audio-feature recipes are supported",
        )
    recipe = target.rebuild_recipe
    if len(recipe.input_artifacts) != 1:
        raise ArtifactRehydrationError(
            "ARTIFACT_REHYDRATION_UNSUPPORTED",
            "rehydration requires exactly one source Audio Artifact",
        )
    parameters = recipe.parameters
    try:
        if isinstance(target, FeatureArtifact):
            return FeatureRehydrateJobPayload(
                target_artifact_id=target.artifact_id,
                source_artifact_id=recipe.input_artifacts[0].artifact_id,
                feature_profile=target.feature_profile,
                timeout_seconds=parameters["timeout_seconds"],
                expected_content_hash=target.content_hash,
                expected_recipe_hash=target.recipe_hash,
            )
        return RehydrateJobPayload(
            target_artifact_id=target.artifact_id,
            source_artifact_id=recipe.input_artifacts[0].artifact_id,
            source_bpm=parameters["source_bpm"],
            target_bpm=parameters["target_bpm"],
            preserve_pitch=parameters["preserve_pitch"],
            timeout_seconds=parameters["timeout_seconds"],
            expected_content_hash=target.content_hash,
            expected_recipe_hash=target.recipe_hash,
        )
    except (KeyError, ValueError) as exc:
        raise ArtifactRehydrationError(
            "ARTIFACT_REHYDRATION_RECIPE_INVALID",
            "the stored rebuild recipe does not satisfy the executable contract",
        ) from exc


class EnqueueFollowupMediaJob:
    """Append one idempotent Job to an existing durable Parent Run."""

    def __init__(
        self,
        uow_factory: MediaJobUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, request: EnqueueFollowupMediaJobRequest) -> EnqueueMediaJobResult:
        fingerprint = request_hash(
            {
                "schema": "media-followup-job-enqueue.v1",
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        async with self._uow_factory() as transaction:
            existing = await transaction.find_media_job_by_key(
                project_id=request.project_id,
                job_type=request.job_type,
                idempotency_key=request.idempotency_key,
            )
            if existing is not None:
                if existing.request_hash != fingerprint or existing.run_id != request.run_id:
                    raise IdempotencyKeyReusedError
                return EnqueueMediaJobResult(
                    run_id=existing.run_id,
                    job_id=existing.job_id,
                    status=existing.status,
                    replayed=True,
                )
            now = self._clock()
            job = MediaJob(
                job_id=self._id_factory(),
                run_id=request.run_id,
                project_id=request.project_id,
                job_type=request.job_type,
                idempotency_key=request.idempotency_key,
                request_hash=fingerprint,
                input_payload=request.input_payload,
                output_quality_profile=request.output_quality_profile,
                max_attempts=request.max_attempts,
                deadline_at=now + timedelta(seconds=request.deadline_seconds),
                created_at=now,
                updated_at=now,
            )
            appended = await transaction.append_media_job_to_run(
                expected_thread_id=request.thread_id,
                job=job,
                run_event_id=self._id_factory(),
                job_event_id=self._id_factory(),
                outbox_event_id=self._id_factory(),
            )
            if not appended:
                raise MediaJobStateConflictError(
                    "the Parent Run is unavailable or belongs to a different import thread"
                )
            return EnqueueMediaJobResult(
                run_id=request.run_id,
                job_id=job.job_id,
                status=job.status,
            )


class ApplyWorkerEvent:
    """Consume one external Worker event exactly once and request Graph continuation."""

    _CONSUMER = "media-worker-completion.v1"

    def __init__(
        self,
        uow_factory: MediaJobUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory

    async def __call__(self, event: WorkerEvent) -> WorkerEventResult:
        async with self._uow_factory() as transaction:
            if await transaction.has_inbox_receipt(
                consumer=self._CONSUMER, event_id=event.event_id
            ):
                job = await transaction.get_media_job(event.job_id)
                if job is None:
                    raise MediaJobNotFoundError
                return _worker_result(job, replayed=True)

            job = await transaction.get_media_job(event.job_id, for_update=True)
            if job is None:
                raise MediaJobNotFoundError
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED_TERMINAL, JobStatus.CANCELLED}:
                if job.status is JobStatus.SUCCEEDED and event.artifact is not None:
                    result_id = job.result_artifact_id
                    if result_id is not None:
                        persisted: AudioArtifact | FeatureArtifact | ExportBundleArtifact | None
                        if isinstance(event.artifact, ExportBundleArtifact):
                            persisted = await transaction.get_export_bundle_artifact(result_id)
                        elif isinstance(event.artifact, FeatureArtifact):
                            persisted = await transaction.get_feature_artifact(result_id)
                        else:
                            persisted = await transaction.get_audio_artifact(result_id)
                        if (
                            persisted is not None
                            and persisted.content_hash == event.artifact.content_hash
                        ):
                            return _worker_result(job, replayed=True)
                raise MediaJobStateConflictError("the job is already terminal")

            artifact = event.artifact
            if artifact is not None:
                if artifact.source_job_id != job.job_id or artifact.project_id != job.project_id:
                    raise MediaJobStateConflictError("artifact does not belong to the target job")
                artifact_profile = (
                    MediaQualityProfile.EXPORT_BUNDLE_V1
                    if isinstance(artifact, ExportBundleArtifact)
                    else artifact.quality_profile
                    if isinstance(artifact, AudioArtifact)
                    else artifact.feature_profile
                )
                expected_profile = job.output_quality_profile or job.output_feature_profile
                if artifact_profile is not expected_profile:
                    raise MediaJobStateConflictError(
                        "artifact quality does not match the job contract"
                    )
            source_update = event.validated_source_artifact
            if source_update is not None:
                if source_update.project_id != job.project_id:
                    raise MediaJobStateConflictError(
                        "validated source artifact does not belong to the target project"
                    )
                persisted_source = await transaction.get_audio_artifact(source_update.artifact_id)
                if (
                    persisted_source is None
                    or persisted_source.source_upload_id != source_update.source_upload_id
                    or persisted_source.content_hash != source_update.content_hash
                ):
                    raise MediaJobStateConflictError(
                        "validated source artifact does not match persisted provenance"
                    )

            if event.event_type == "job.completed":
                status = JobStatus.SUCCEEDED
                run_status = RunStatus.SUCCEEDED
                topic = "graph.resume.requested"
                artifact_id = artifact.artifact_id if artifact is not None else None
            elif event.event_type == "job.failed_retryable":
                status = JobStatus.FAILED_RETRYABLE
                run_status = RunStatus.WAITING_WORKER
                topic = "media.job.retry.requested"
                artifact_id = None
            else:
                status = JobStatus.FAILED_TERMINAL
                run_status = RunStatus.FAILED
                topic = "graph.resume.requested"
                artifact_id = None

            updated = job.model_copy(
                update={
                    "status": status,
                    "result_artifact_id": artifact_id,
                    "error_code": event.error_code,
                    "updated_at": event.occurred_at,
                }
            )
            persisted_artifact = await transaction.apply_worker_event(
                event=event,
                updated_job=updated,
                run_status=run_status,
                artifact=artifact,
                feature_artifacts=event.feature_artifacts,
                validated_source_artifact=source_update,
                consumer=self._CONSUMER,
                inbox_receipt_id=self._id_factory(),
                run_event_id=self._id_factory(),
                job_event_id=self._id_factory(),
                outbox_event_id=self._id_factory(),
                outbox_topic=topic,
            )
            if persisted_artifact is not None and persisted_artifact.artifact_id != artifact_id:
                updated = updated.model_copy(
                    update={"result_artifact_id": persisted_artifact.artifact_id}
                )
            return _worker_result(updated, replayed=False)


def _worker_result(job: MediaJob, *, replayed: bool) -> WorkerEventResult:
    return WorkerEventResult(
        run_id=job.run_id,
        job_id=job.job_id,
        status=job.status,
        artifact_id=job.result_artifact_id,
        replayed=replayed,
    )
