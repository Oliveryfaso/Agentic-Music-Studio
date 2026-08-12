"""Execute one persisted media Job and commit one idempotent Worker event."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError

from motif_forge.application.errors import MediaJobNotFoundError
from motif_forge.application.media_jobs import ApplyWorkerEvent
from motif_forge.application.ports import MediaJobTransaction
from motif_forge.audio.features import FeatureOutput, write_feature_for_profile
from motif_forge.audio.ingest import AudioIngestError, LocalAudioIngestor, NormalizedAudio
from motif_forge.audio.time_stretch import (
    LocalTimeStretchWorkspace,
    PitchPreservingTimeStretch,
    TimeStretchError,
    TimeStretchRequest,
    TimeStretchResult,
)
from motif_forge.config import Settings
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    ArtifactValidationStatus,
    AudioArtifact,
    FeatureArtifact,
    FeatureProfile,
    FeatureRehydrateJobPayload,
    IngestJobPayload,
    JobStatus,
    MediaJob,
    MediaJobType,
    MediaQualityProfile,
    RebuildInputArtifact,
    RebuildRecipe,
    RehydrateJobPayload,
    TimeStretchJobPayload,
    WorkerEvent,
)
from motif_forge.infrastructure.persistence.database import (
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerExecutionResult:
    job_id: UUID
    status: str
    artifact_id: UUID | None = None
    error_code: str | None = None


async def execute_media_job(
    job_id: UUID,
    *,
    settings: Settings,
    worker_id: str,
) -> WorkerExecutionResult:
    """Claim, execute and record one Job; duplicate delivery is a safe no-op."""

    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required by the media Worker")
    engine = create_postgres_engine(settings.postgres_dsn.get_secret_value())
    uow = PostgresMediaJobUnitOfWork(create_session_factory(engine))
    try:
        now = datetime.now(UTC)
        async with uow() as transaction:
            current = await transaction.get_media_job(job_id)
            if current is None:
                raise MediaJobNotFoundError
            claimed = await transaction.claim_media_job(
                job_id,
                worker_id=worker_id,
                now=now,
                lease_expires_at=now + timedelta(seconds=settings.media_job_lease_seconds),
            )
        if claimed is None:
            return await _resolve_unclaimed_job(current, uow)

        try:
            media_result: TimeStretchResult | NormalizedAudio | FeatureOutput
            async with uow() as transaction:
                source = await _load_source(transaction, claimed)
            if claimed.job_type in {MediaJobType.TIME_STRETCH, MediaJobType.REHYDRATE}:
                media_result = await _execute_time_stretch(claimed, source, settings)
                source_update = None
            elif claimed.job_type is MediaJobType.REHYDRATE_FEATURE:
                media_result = await _execute_feature_rehydrate(claimed, source, settings)
                source_update = None
            elif claimed.job_type is MediaJobType.INGEST:
                source_update, media_result = await _execute_ingest(claimed, source, settings)
            else:
                raise TimeStretchError(
                    "MEDIA_JOB_TYPE_UNSUPPORTED",
                    "This Worker does not support the requested Job type.",
                )
        except (TimeStretchError, AudioIngestError) as exc:
            return await _record_failure(claimed, uow, exc.code, retryable=exc.retryable)
        except ValidationError:
            return await _record_failure(claimed, uow, "MEDIA_JOB_SCHEMA_INVALID", retryable=False)
        except Exception:
            logger.exception(
                "unexpected media Worker failure",
                extra={"job_id": str(claimed.job_id), "job_type": claimed.job_type.value},
            )
            return await _record_failure(
                claimed, uow, "MEDIA_WORKER_UNEXPECTED_FAILURE", retryable=False
            )

        heartbeat_at = datetime.now(UTC)
        async with uow() as transaction:
            await transaction.heartbeat_media_job(
                claimed.job_id,
                worker_id=worker_id,
                now=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=settings.media_job_lease_seconds),
                progress_percent=90,
            )
        if heartbeat_at > claimed.deadline_at:
            return await _record_failure(
                claimed, uow, "MEDIA_JOB_DEADLINE_EXCEEDED", retryable=False
            )

        if claimed.job_type is MediaJobType.REHYDRATE_FEATURE:
            assert isinstance(media_result, FeatureOutput)
            feature_payload = _parse_feature_rehydrate_payload(claimed)
            feature_artifact = _rehydrated_feature_artifact(
                output=media_result,
                source=source,
                job=claimed,
                payload=feature_payload,
                created_at=heartbeat_at,
            )
            event = WorkerEvent(
                event_id=(
                    f"job:{claimed.job_id}:attempt:{claimed.attempts}:completed:"
                    f"{media_result.sha256}"
                ),
                job_id=claimed.job_id,
                event_type="job.completed",
                artifact=feature_artifact,
                occurred_at=heartbeat_at,
            )
            persisted = await ApplyWorkerEvent(uow)(event)
            return WorkerExecutionResult(
                job_id=claimed.job_id,
                status=persisted.status.value,
                artifact_id=persisted.artifact_id,
            )
        if claimed.job_type is MediaJobType.INGEST:
            assert isinstance(media_result, NormalizedAudio)
            duration_seconds = media_result.probe.duration_seconds
            checksum = media_result.sha256
            byte_size = media_result.byte_size
            storage_key = media_result.storage_key
            recipe_hash = media_result.recipe_hash
            encoder = "ffmpeg"
            encoder_version = media_result.engine_version
            lifecycle = ArtifactLifecycle.PROTECTED
            media_role = "normalized_import_audio"
            analysis = media_result.analysis
        else:
            assert isinstance(media_result, TimeStretchResult)
            duration_seconds = media_result.quality.actual_duration_seconds
            checksum = media_result.artifact.sha256
            byte_size = media_result.artifact.byte_size
            storage_key = media_result.artifact.storage_key
            recipe_hash = media_result.recipe_hash
            encoder = media_result.engine
            encoder_version = media_result.engine_version
            lifecycle = ArtifactLifecycle.REBUILDABLE
            media_role = "time_stretched_audio"
            analysis = None
        rebuild_recipe = None
        if claimed.job_type in {MediaJobType.TIME_STRETCH, MediaJobType.REHYDRATE}:
            payload = _stretch_parameters(claimed)
            rebuild_recipe = RebuildRecipe(
                recipe_id=uuid5(NAMESPACE_URL, f"motif-forge:rebuild:{recipe_hash}"),
                recipe_kind="time_stretch",
                input_artifacts=(
                    RebuildInputArtifact(
                        artifact_id=source.artifact_id,
                        content_hash=source.content_hash,
                    ),
                ),
                parameters={
                    "source_bpm": payload.source_bpm,
                    "target_bpm": payload.target_bpm,
                    "preserve_pitch": True,
                    "timeout_seconds": payload.timeout_seconds,
                },
                engine=encoder,
                engine_version=encoder_version,
                policy_version="time-stretch-quality-policy.v1",
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                expected_container="wav",
                expected_codec="pcm",
                expected_sample_rate_hz=48_000,
                expected_channels=2,
                expected_bit_depth=16,
                validation_rules=(
                    "duration-tolerance.v1",
                    "pitch-deviation-25-cents.v1",
                    "silence-and-click-gate.v1",
                ),
                idempotency_key=f"rehydrate:{recipe_hash}",
            )
            recipe_hash = rebuild_recipe.content_hash
        if claimed.job_type is MediaJobType.REHYDRATE:
            assert isinstance(media_result, TimeStretchResult)
            rehydrate_payload = _parse_rehydrate_payload(claimed)
            if checksum != rehydrate_payload.expected_content_hash:
                return await _record_failure(
                    claimed,
                    uow,
                    "ARTIFACT_REHYDRATION_CHECKSUM_MISMATCH",
                    retryable=False,
                )
            if recipe_hash != rehydrate_payload.expected_recipe_hash:
                return await _record_failure(
                    claimed,
                    uow,
                    "ARTIFACT_REHYDRATION_RECIPE_MISMATCH",
                    retryable=False,
                )
        audio_artifact = AudioArtifact(
            artifact_id=(
                _parse_rehydrate_payload(claimed).target_artifact_id
                if claimed.job_type is MediaJobType.REHYDRATE
                else uuid4()
            ),
            project_id=claimed.project_id,
            source_job_id=claimed.job_id,
            content_hash=checksum,
            byte_size=byte_size,
            storage_key=storage_key,
            media_role=media_role,
            quality_profile=MediaQualityProfile.WORKING_PCM_V1,
            container="wav",
            codec="pcm",
            sample_rate_hz=48_000,
            channels=2,
            duration_seconds=duration_seconds,
            bit_depth=16,
            encoder=encoder,
            encoder_version=encoder_version,
            lifecycle_class=lifecycle,
            recipe_hash=recipe_hash,
            rebuild_recipe=rebuild_recipe,
            analysis=analysis,
            created_at=heartbeat_at,
            last_accessed_at=heartbeat_at,
        )
        feature_artifacts: tuple[FeatureArtifact, ...] = ()
        if claimed.job_type is MediaJobType.INGEST:
            assert isinstance(media_result, NormalizedAudio)
            feature_artifacts = tuple(
                _feature_artifact(
                    output=output,
                    source=audio_artifact,
                    job=claimed,
                    created_at=heartbeat_at,
                    engine_version=media_result.engine_version,
                )
                for output in media_result.feature_outputs
            )
        event = WorkerEvent(
            event_id=(f"job:{claimed.job_id}:attempt:{claimed.attempts}:completed:{checksum}"),
            job_id=claimed.job_id,
            event_type="job.completed",
            artifact=audio_artifact,
            feature_artifacts=feature_artifacts,
            validated_source_artifact=source_update,
            occurred_at=heartbeat_at,
        )
        persisted = await ApplyWorkerEvent(uow)(event)
        return WorkerExecutionResult(
            job_id=claimed.job_id,
            status=persisted.status.value,
            artifact_id=persisted.artifact_id,
        )
    finally:
        await engine.dispose()


def _feature_artifact(
    *,
    output: object,
    source: AudioArtifact,
    job: MediaJob,
    created_at: datetime,
    engine_version: str,
) -> FeatureArtifact:
    if not isinstance(output, FeatureOutput):
        raise TypeError("invalid Feature output")
    recipe = RebuildRecipe(
        recipe_id=uuid5(NAMESPACE_URL, f"motif-forge:feature-rebuild:{output.sha256}"),
        recipe_kind="analysis",
        input_artifacts=(
            RebuildInputArtifact(
                artifact_id=source.artifact_id,
                content_hash=source.content_hash,
            ),
        ),
        parameters={
            "feature_profile": output.feature_profile.value,
            "feature_schema_version": output.feature_schema_version,
            "timeout_seconds": 60.0,
        },
        engine="motif-forge-audio-features",
        engine_version=engine_version,
        policy_version="audio-feature-policy.v1",
        output_feature_profile=output.feature_profile,
        validation_rules=("json-schema.v1", "source-content-hash.v1"),
        idempotency_key=f"feature:{source.content_hash}:{output.feature_profile.value}",
    )
    return FeatureArtifact(
        artifact_id=uuid5(
            NAMESPACE_URL,
            f"motif-forge:feature:{job.project_id}:{output.feature_profile.value}:{output.sha256}",
        ),
        project_id=job.project_id,
        source_job_id=job.job_id,
        source_audio_artifact_id=source.artifact_id,
        source_audio_content_hash=source.content_hash,
        content_hash=output.sha256,
        byte_size=output.byte_size,
        storage_key=output.storage_key,
        feature_profile=FeatureProfile(output.feature_profile),
        feature_schema_version=output.feature_schema_version,
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=created_at,
        last_accessed_at=created_at,
    )


def _rehydrated_feature_artifact(
    *,
    output: FeatureOutput,
    source: AudioArtifact,
    job: MediaJob,
    payload: FeatureRehydrateJobPayload,
    created_at: datetime,
) -> FeatureArtifact:
    recipe = RebuildRecipe(
        recipe_id=uuid5(NAMESPACE_URL, f"motif-forge:feature-rebuild:{output.sha256}"),
        recipe_kind="analysis",
        input_artifacts=(
            RebuildInputArtifact(artifact_id=source.artifact_id, content_hash=source.content_hash),
        ),
        parameters={
            "feature_profile": output.feature_profile.value,
            "feature_schema_version": output.feature_schema_version,
            "timeout_seconds": payload.timeout_seconds,
        },
        engine="motif-forge-audio-features",
        engine_version=source.encoder_version,
        policy_version="audio-feature-policy.v1",
        output_feature_profile=output.feature_profile,
        validation_rules=("json-schema.v1", "source-content-hash.v1"),
        idempotency_key=f"feature:{source.content_hash}:{output.feature_profile.value}",
    )
    return FeatureArtifact(
        artifact_id=payload.target_artifact_id,
        project_id=job.project_id,
        source_job_id=job.job_id,
        source_audio_artifact_id=source.artifact_id,
        source_audio_content_hash=source.content_hash,
        content_hash=output.sha256,
        byte_size=output.byte_size,
        storage_key=output.storage_key,
        feature_profile=output.feature_profile,
        feature_schema_version=output.feature_schema_version,
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=created_at,
        last_accessed_at=created_at,
    )


async def _load_source(transaction: MediaJobTransaction, job: MediaJob) -> AudioArtifact:
    if job.job_type not in {
        MediaJobType.TIME_STRETCH,
        MediaJobType.REHYDRATE,
        MediaJobType.REHYDRATE_FEATURE,
        MediaJobType.INGEST,
    }:
        raise TimeStretchError(
            "MEDIA_JOB_TYPE_UNSUPPORTED", "This Worker does not support the requested Job type."
        )
    expected_profile = (
        job.output_feature_profile is not None
        if job.job_type is MediaJobType.REHYDRATE_FEATURE
        else job.output_quality_profile is MediaQualityProfile.WORKING_PCM_V1
    )
    if not expected_profile:
        raise TimeStretchError(
            "MEDIA_OUTPUT_PROFILE_INVALID",
            "This media operation must produce the working PCM quality profile.",
        )
    try:
        source_artifact_id = (
            _stretch_source_artifact_id(job)
            if job.job_type in {MediaJobType.TIME_STRETCH, MediaJobType.REHYDRATE}
            else _parse_feature_rehydrate_payload(job).source_artifact_id
            if job.job_type is MediaJobType.REHYDRATE_FEATURE
            else _parse_ingest_payload(job).source_artifact_id
        )
    except ValidationError as exc:
        raise TimeStretchError(
            "MEDIA_JOB_SCHEMA_INVALID", "The persisted Job payload is invalid."
        ) from exc
    source = await transaction.get_audio_artifact(source_artifact_id)
    if source is None or source.project_id != job.project_id:
        raise TimeStretchError("SOURCE_ARTIFACT_UNAVAILABLE", "The source Artifact is unavailable.")
    if source.availability is not ArtifactAvailability.AVAILABLE:
        raise TimeStretchError("SOURCE_ARTIFACT_UNAVAILABLE", "The source Artifact is unavailable.")
    return source


async def _execute_ingest(
    job: MediaJob, source: AudioArtifact, settings: Settings
) -> tuple[AudioArtifact, NormalizedAudio]:
    if (
        source.quality_profile is not MediaQualityProfile.SOURCE_ORIGINAL_V1
        or source.validation_status is not ArtifactValidationStatus.QUARANTINED
    ):
        raise AudioIngestError(
            "INGEST_SOURCE_STATE_INVALID", "ingest requires a quarantined source-original Artifact"
        )
    payload = _parse_ingest_payload(job)
    ingestor = LocalAudioIngestor(settings.artifact_root)
    source_probe, normalized = await asyncio.to_thread(
        ingestor.run,
        job_id=job.job_id,
        project_id=job.project_id,
        source_storage_key=source.storage_key,
        source_hash=source.content_hash,
        timeout_seconds=payload.timeout_seconds,
    )
    source_values = source.model_dump(mode="python")
    source_values.update(
        {
            "codec": source_probe.codec,
            "sample_rate_hz": source_probe.sample_rate_hz,
            "channels": source_probe.channels,
            "duration_seconds": source_probe.duration_seconds,
            "bitrate_kbps": source_probe.bitrate_kbps,
            "bit_depth": source_probe.bit_depth,
            "validation_status": ArtifactValidationStatus.VALIDATED,
        }
    )
    validated = AudioArtifact.model_validate(source_values)
    return validated, normalized


async def _execute_time_stretch(
    job: MediaJob, source: AudioArtifact, settings: Settings
) -> TimeStretchResult:
    payload = _stretch_parameters(job)
    workspace = LocalTimeStretchWorkspace(
        settings.artifact_root,
        source_storage_keys={source.artifact_id: source.storage_key},
    )
    operator = PitchPreservingTimeStretch(workspace)
    request = TimeStretchRequest(
        job_id=job.job_id,
        source_artifact_id=source.artifact_id,
        source_bpm=payload.source_bpm,
        target_bpm=payload.target_bpm,
        preserve_pitch=payload.preserve_pitch,
        timeout_seconds=payload.timeout_seconds,
    )
    return await asyncio.to_thread(operator.run, request)


async def _execute_feature_rehydrate(
    job: MediaJob, source: AudioArtifact, settings: Settings
) -> FeatureOutput:
    payload = _parse_feature_rehydrate_payload(job)
    source_path = (settings.artifact_root.resolve() / source.storage_key).resolve()
    root = settings.artifact_root.resolve()
    if not source_path.is_relative_to(root) or not source_path.is_file():
        raise AudioIngestError(
            "SOURCE_ARTIFACT_UNAVAILABLE", "Feature source bytes are unavailable"
        )
    output = await asyncio.to_thread(
        write_feature_for_profile,
        source_path,
        artifact_root=settings.artifact_root,
        project_id=job.project_id,
        source_content_hash=source.content_hash,
        profile=payload.feature_profile,
    )
    if output.sha256 != payload.expected_content_hash:
        raise AudioIngestError(
            "ARTIFACT_REHYDRATION_CHECKSUM_MISMATCH", "Feature checksum changed"
        )
    return output


def _parse_time_stretch_payload(job: MediaJob) -> TimeStretchJobPayload:
    return TimeStretchJobPayload.model_validate_json(json.dumps(job.input_payload), strict=True)


def _parse_rehydrate_payload(job: MediaJob) -> RehydrateJobPayload:
    return RehydrateJobPayload.model_validate_json(json.dumps(job.input_payload), strict=True)


def _parse_feature_rehydrate_payload(job: MediaJob) -> FeatureRehydrateJobPayload:
    return FeatureRehydrateJobPayload.model_validate_json(
        json.dumps(job.input_payload), strict=True
    )


def _stretch_parameters(job: MediaJob) -> TimeStretchJobPayload | RehydrateJobPayload:
    if job.job_type is MediaJobType.REHYDRATE:
        return _parse_rehydrate_payload(job)
    return _parse_time_stretch_payload(job)


def _stretch_source_artifact_id(job: MediaJob) -> UUID:
    return _stretch_parameters(job).source_artifact_id


def _parse_ingest_payload(job: MediaJob) -> IngestJobPayload:
    return IngestJobPayload.model_validate_json(json.dumps(job.input_payload), strict=True)


async def _resolve_unclaimed_job(
    job: MediaJob, uow: PostgresMediaJobUnitOfWork
) -> WorkerExecutionResult:
    if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED_TERMINAL, JobStatus.CANCELLED}:
        return WorkerExecutionResult(
            job_id=job.job_id,
            status=job.status.value,
            artifact_id=job.result_artifact_id,
            error_code=job.error_code,
        )
    now = datetime.now(UTC)
    if job.deadline_at <= now:
        return await _record_failure(job, uow, "MEDIA_JOB_DEADLINE_EXCEEDED", retryable=False)
    if job.attempts >= job.max_attempts:
        return await _record_failure(job, uow, "MEDIA_JOB_ATTEMPTS_EXHAUSTED", retryable=False)
    return WorkerExecutionResult(job_id=job.job_id, status="already_running")


async def _record_failure(
    job: MediaJob,
    uow: PostgresMediaJobUnitOfWork,
    error_code: str,
    *,
    retryable: bool,
) -> WorkerExecutionResult:
    now = datetime.now(UTC)
    can_retry = retryable and job.attempts < job.max_attempts and now < job.deadline_at
    event_type: Literal["job.failed_retryable", "job.failed_terminal"] = (
        "job.failed_retryable" if can_retry else "job.failed_terminal"
    )
    event = WorkerEvent(
        event_id=f"job:{job.job_id}:attempt:{job.attempts}:{event_type}:{error_code}",
        job_id=job.job_id,
        event_type=event_type,
        error_code=error_code,
        occurred_at=now,
    )
    persisted = await ApplyWorkerEvent(uow)(event)
    return WorkerExecutionResult(
        job_id=job.job_id,
        status=persisted.status.value,
        error_code=error_code,
    )
