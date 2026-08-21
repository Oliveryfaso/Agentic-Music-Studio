"""Execute one persisted media Job and commit one idempotent Worker event."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError

from motif_forge.application.errors import MediaJobNotFoundError, MediaJobStateConflictError
from motif_forge.application.exporting import write_export_bundle
from motif_forge.application.media_jobs import ApplyWorkerEvent, WorkerEventResult
from motif_forge.application.ports import MediaJobTransaction
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.application.storage import (
    LocalArtifactCollector,
    LocalStorageRootInspector,
    PersistentStorageEventRecorder,
    PostgresStorageFactsLoader,
    RunStoragePressureGate,
)
from motif_forge.audio.chromium_render import (
    CanonicalRenderResult,
    ChromiumRenderClient,
    ChromiumRenderError,
)
from motif_forge.audio.features import FeatureOutput, write_feature_for_profile
from motif_forge.audio.ingest import AudioIngestError, LocalAudioIngestor, NormalizedAudio
from motif_forge.audio.time_stretch import (
    LocalTimeStretchWorkspace,
    PitchPreservingTimeStretch,
    TimeStretchError,
    TimeStretchRequest,
    TimeStretchResult,
)
from motif_forge.audio.transcode import (
    ExportTranscodeError,
    Mp3TranscodeResult,
    transcode_master_to_mp3,
)
from motif_forge.config import Settings
from motif_forge.domain.exporting import AudioExportRef, ExportBundleRequest
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    ArtifactValidationStatus,
    AudioArtifact,
    BundleAudioInput,
    CandidatePreviewJobPayload,
    CanonicalRenderJobPayload,
    ExportBundleArtifact,
    ExportBundleJobPayload,
    ExportMp3JobPayload,
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
    RenderScope,
    TimeStretchJobPayload,
    WorkerEvent,
)
from motif_forge.domain.revisions import CandidateSnapshot
from motif_forge.domain.storage import StorageRoute
from motif_forge.infrastructure.persistence.database import (
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerExecutionResult:
    job_id: UUID
    status: str
    artifact_id: UUID | None = None
    error_code: str | None = None


class _PersistedJobCancelled(RuntimeError):
    pass


def validate_candidate_preview_lineage(
    payload: CandidatePreviewJobPayload, snapshot: CandidateSnapshot
) -> None:
    projection = compile_audio_graph(snapshot.candidate_ir)
    if (
        snapshot.project_id != payload.project_id
        or snapshot.candidate_snapshot_id != payload.candidate_snapshot_id
        or snapshot.candidate_content_hash != payload.candidate_content_hash
        or projection.arrangement_hash != payload.candidate_content_hash
        or projection.graph_hash != payload.audio_graph_hash
        or projection.graph != payload.audio_graph
    ):
        raise ChromiumRenderError("CANDIDATE_PREVIEW_LINEAGE_MISMATCH")


def _candidate_preview_rebuild_recipe(payload: CandidatePreviewJobPayload) -> RebuildRecipe:
    return RebuildRecipe(
        recipe_id=uuid5(
            NAMESPACE_URL,
            f"motif-forge:candidate-preview-rebuild:{payload.candidate_snapshot_id}:"
            f"{payload.audio_graph_hash}:{payload.seed}",
        ),
        recipe_kind="render",
        parameters={
            "candidate_snapshot_id": str(payload.candidate_snapshot_id),
            "candidate_content_hash": payload.candidate_content_hash,
            "audio_graph": payload.audio_graph,
            "audio_graph_hash": payload.audio_graph_hash,
            "audio_engine_version": payload.audio_engine_version,
            "seed": payload.seed,
            "bitrate_kbps": payload.bitrate_kbps,
            "timeout_seconds": payload.timeout_seconds,
            "maximum_output_bytes": payload.maximum_output_bytes,
        },
        engine="motif-forge-chromium-renderer+ffmpeg-libmp3lame",
        engine_version=payload.audio_engine_version,
        policy_version="candidate-preview-render.v1",
        output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        expected_container="mp3",
        expected_codec="mp3",
        expected_sample_rate_hz=48_000,
        expected_channels=2,
        validation_rules=(
            "candidate-snapshot-lineage.v1",
            "duration-tolerance.v1",
            "non-silence.v1",
        ),
        idempotency_key=f"candidate-preview:{payload.candidate_snapshot_id}",
    )


async def _await_work_or_cancellation(
    work: Awaitable[Any],
    *,
    job_id: UUID,
    uow: PostgresMediaJobUnitOfWork,
    on_cancel: Callable[[], None] | None = None,
) -> Any:
    task = asyncio.ensure_future(work)
    while not task.done():
        await asyncio.wait({task}, timeout=0.25)
        # A completed side effect must be returned to the caller so the authoritative
        # heartbeat/event boundary can either register it or clean it up. Cancelling a
        # completed task here would discard the only `created_new` cleanup evidence.
        if task.done():
            return await task
        async with uow() as transaction:
            current = await transaction.get_media_job(job_id)
        if current is not None and current.status is JobStatus.CANCELLED:
            if on_cancel is not None:
                on_cancel()
                try:
                    # Thread-backed operators use the event to stop before promotion.
                    # Waiting also preserves a result if promotion won the race.
                    return await task
                except Exception as exc:
                    raise _PersistedJobCancelled from exc
            task.cancel()
            try:
                # If completion won between the status read and cancellation, return
                # its cleanup evidence instead of discarding it.
                return await task
            except asyncio.CancelledError as exc:
                raise _PersistedJobCancelled from exc
    return await task


def _cleanup_cancelled_output(
    media_result: object, *, artifact_root: Path
) -> None:
    key: str | None = None
    created_new = False
    if isinstance(media_result, (CanonicalRenderResult, Mp3TranscodeResult)):
        key = media_result.storage_key
        created_new = media_result.created_new
    elif isinstance(media_result, tuple) and isinstance(media_result[1], ExportBundleArtifact):
        key = media_result[1].storage_prefix
        created_new = media_result[1].created_new
    elif isinstance(media_result, tuple) and isinstance(media_result[1], Mp3TranscodeResult):
        key = media_result[1].storage_key
        created_new = media_result[1].created_new
    if not created_new or key is None:
        return
    root = artifact_root.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        return
    if path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        import shutil

        shutil.rmtree(path)


async def _apply_worker_event_fail_closed(
    event: WorkerEvent,
    *,
    uow: PostgresMediaJobUnitOfWork,
    media_result: object,
    artifact_root: Path,
) -> WorkerEventResult:
    try:
        return await ApplyWorkerEvent(uow)(event)
    except MediaJobStateConflictError:
        async with uow() as transaction:
            current = await transaction.get_media_job(event.job_id)
        if current is None:
            _cleanup_cancelled_output(media_result, artifact_root=artifact_root)
            raise
        if current.status is JobStatus.SUCCEEDED:
            persisted: AudioArtifact | FeatureArtifact | ExportBundleArtifact | None = None
            artifact = event.artifact
            if current.result_artifact_id is not None and artifact is not None:
                async with uow() as transaction:
                    if isinstance(artifact, ExportBundleArtifact):
                        persisted = await transaction.get_export_bundle_artifact(
                            current.result_artifact_id
                        )
                    elif isinstance(artifact, FeatureArtifact):
                        persisted = await transaction.get_feature_artifact(
                            current.result_artifact_id
                        )
                    else:
                        persisted = await transaction.get_audio_artifact(
                            current.result_artifact_id
                        )
            if _same_authoritative_artifact(persisted, artifact):
                return WorkerEventResult(
                    run_id=current.run_id,
                    job_id=current.job_id,
                    status=current.status,
                    artifact_id=current.result_artifact_id,
                    replayed=True,
                )
            _cleanup_cancelled_output(media_result, artifact_root=artifact_root)
            raise
        _cleanup_cancelled_output(media_result, artifact_root=artifact_root)
        if current.status not in {JobStatus.FAILED_TERMINAL, JobStatus.CANCELLED}:
            raise
        return WorkerEventResult(
            run_id=current.run_id,
            job_id=current.job_id,
            status=current.status,
            artifact_id=None,
            replayed=False,
        )


def _same_authoritative_artifact(persisted: object, candidate: object) -> bool:
    if type(persisted) is not type(candidate):
        return False
    if isinstance(persisted, AudioArtifact) and isinstance(candidate, AudioArtifact):
        return (
            persisted.artifact_id == candidate.artifact_id
            and persisted.content_hash == candidate.content_hash
            and persisted.project_id == candidate.project_id
            and persisted.source_job_id == candidate.source_job_id
            and persisted.revision_id == candidate.revision_id
            and persisted.candidate_snapshot_id == candidate.candidate_snapshot_id
            and persisted.arrangement_hash == candidate.arrangement_hash
            and persisted.render_scope == candidate.render_scope
            and persisted.render_track_ids == candidate.render_track_ids
            and persisted.storage_key == candidate.storage_key
            and persisted.quality_profile == candidate.quality_profile
        )
    if isinstance(persisted, FeatureArtifact) and isinstance(candidate, FeatureArtifact):
        return (
            persisted.artifact_id == candidate.artifact_id
            and persisted.content_hash == candidate.content_hash
            and persisted.project_id == candidate.project_id
            and persisted.source_job_id == candidate.source_job_id
            and persisted.source_audio_artifact_id == candidate.source_audio_artifact_id
            and persisted.source_audio_content_hash == candidate.source_audio_content_hash
            and persisted.storage_key == candidate.storage_key
            and persisted.feature_profile == candidate.feature_profile
        )
    if isinstance(persisted, ExportBundleArtifact) and isinstance(
        candidate, ExportBundleArtifact
    ):
        return (
            persisted.artifact_id == candidate.artifact_id
            and persisted.content_hash == candidate.content_hash
            and persisted.project_id == candidate.project_id
            and persisted.source_job_id == candidate.source_job_id
            and persisted.revision_id == candidate.revision_id
            and persisted.arrangement_hash == candidate.arrangement_hash
            and persisted.storage_prefix == candidate.storage_prefix
            and persisted.input_artifact_ids == candidate.input_artifact_ids
        )
    return False


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

        storage_failure = await _run_artifact_storage_gate(claimed, settings, uow)
        if storage_failure is not None:
            return await _record_failure(
                claimed,
                uow,
                storage_failure,
                retryable=storage_failure
                in {"ARTIFACT_ROOT_UNAVAILABLE", "STORAGE_QUOTA_EXCEEDED"},
            )

        try:
            media_result: (
                TimeStretchResult
                | NormalizedAudio
                | FeatureOutput
                | CanonicalRenderResult
                | Mp3TranscodeResult
                | tuple[CandidatePreviewJobPayload, Mp3TranscodeResult]
                | tuple[ExportBundleJobPayload, ExportBundleArtifact]
            )
            source: AudioArtifact | None = None
            if claimed.job_type not in {
                MediaJobType.RENDER_PREVIEW,
                MediaJobType.RENDER_CANONICAL,
                MediaJobType.EXPORT_BUNDLE,
            }:
                async with uow() as transaction:
                    source = await _load_source(transaction, claimed)
            if claimed.job_type is MediaJobType.RENDER_PREVIEW:
                cancel_event = threading.Event()
                media_result = await _await_work_or_cancellation(
                    _execute_candidate_preview(
                        claimed, uow, settings, cancel_event=cancel_event
                    ),
                    job_id=claimed.job_id,
                    uow=uow,
                    on_cancel=cancel_event.set,
                )
                source_update = None
            elif claimed.job_type is MediaJobType.RENDER_CANONICAL:
                media_result = await _await_work_or_cancellation(
                    _execute_canonical_render(claimed, uow, settings),
                    job_id=claimed.job_id,
                    uow=uow,
                )
                source_update = None
            elif claimed.job_type is MediaJobType.EXPORT_BUNDLE:
                cancel_event = threading.Event()
                media_result = await _await_work_or_cancellation(
                    _execute_export_bundle(claimed, uow, settings, cancel_event=cancel_event),
                    job_id=claimed.job_id,
                    uow=uow,
                    on_cancel=cancel_event.set,
                )
                source_update = None
            elif claimed.job_type is MediaJobType.TRANSCODE_EXPORT:
                assert source is not None
                cancel_event = threading.Event()
                media_result = await _await_work_or_cancellation(
                    _execute_export_transcode(
                        claimed, source, settings, cancel_event=cancel_event
                    ),
                    job_id=claimed.job_id,
                    uow=uow,
                    on_cancel=cancel_event.set,
                )
                source_update = None
            elif claimed.job_type in {MediaJobType.TIME_STRETCH, MediaJobType.REHYDRATE}:
                assert source is not None
                media_result = await _execute_time_stretch(claimed, source, settings)
                source_update = None
            elif claimed.job_type is MediaJobType.REHYDRATE_FEATURE:
                assert source is not None
                media_result = await _execute_feature_rehydrate(claimed, source, settings)
                source_update = None
            elif claimed.job_type is MediaJobType.INGEST:
                assert source is not None
                source_update, media_result = await _execute_ingest(claimed, source, settings)
            else:
                raise TimeStretchError(
                    "MEDIA_JOB_TYPE_UNSUPPORTED",
                    "This Worker does not support the requested Job type.",
                )
        except _PersistedJobCancelled:
            return WorkerExecutionResult(
                job_id=claimed.job_id,
                status=JobStatus.CANCELLED.value,
                error_code="MEDIA_JOB_CANCELLED",
            )
        except (
            TimeStretchError,
            AudioIngestError,
            ChromiumRenderError,
            ExportTranscodeError,
        ) as exc:
            code = exc.code if hasattr(exc, "code") else str(exc)
            retryable = getattr(exc, "retryable", False)
            return await _record_failure(claimed, uow, code, retryable=retryable)
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
            heartbeat_recorded = await transaction.heartbeat_media_job(
                claimed.job_id,
                worker_id=worker_id,
                now=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=settings.media_job_lease_seconds),
                progress_percent=90,
            )
            current_after_work = await transaction.get_media_job(claimed.job_id)
        if not heartbeat_recorded:
            if current_after_work is None or current_after_work.status is not JobStatus.SUCCEEDED:
                _cleanup_cancelled_output(media_result, artifact_root=settings.artifact_root)
            return WorkerExecutionResult(
                job_id=claimed.job_id,
                status=(
                    current_after_work.status.value
                    if current_after_work is not None
                    else "lease_lost"
                ),
                artifact_id=(
                    current_after_work.result_artifact_id
                    if current_after_work is not None
                    else None
                ),
                error_code=(
                    current_after_work.error_code
                    if current_after_work is not None
                    else "MEDIA_JOB_LEASE_LOST"
                ),
            )
        if heartbeat_at > claimed.deadline_at:
            _cleanup_cancelled_output(media_result, artifact_root=settings.artifact_root)
            return await _record_failure(
                claimed, uow, "MEDIA_JOB_DEADLINE_EXCEEDED", retryable=False
            )

        if claimed.job_type is MediaJobType.RENDER_PREVIEW:
            assert isinstance(media_result, tuple)
            preview_payload, preview_mp3 = media_result
            assert isinstance(preview_payload, CandidatePreviewJobPayload)
            assert isinstance(preview_mp3, Mp3TranscodeResult)
            recipe = _candidate_preview_rebuild_recipe(preview_payload)
            audio_artifact = AudioArtifact(
                artifact_id=preview_payload.target_artifact_id or uuid4(),
                project_id=claimed.project_id,
                candidate_snapshot_id=preview_payload.candidate_snapshot_id,
                arrangement_hash=preview_payload.candidate_content_hash,
                render_scope=RenderScope.MASTER,
                source_job_id=claimed.job_id,
                content_hash=preview_mp3.sha256,
                byte_size=preview_mp3.byte_size,
                storage_key=preview_mp3.storage_key,
                media_role="candidate_preview",
                quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
                container="mp3",
                codec="mp3",
                sample_rate_hz=preview_mp3.sample_rate_hz,
                channels=preview_mp3.channels,
                duration_seconds=preview_mp3.duration_seconds,
                bitrate_kbps=preview_mp3.bitrate_kbps,
                encoder="ffmpeg-libmp3lame",
                encoder_version="ffmpeg-system.v1",
                lifecycle_class=ArtifactLifecycle.REBUILDABLE,
                recipe_hash=recipe.content_hash,
                rebuild_recipe=recipe,
                created_at=heartbeat_at,
                last_accessed_at=heartbeat_at,
            )
            event = WorkerEvent(
                event_id=(
                    f"job:{claimed.job_id}:attempt:{claimed.attempts}:completed:"
                    f"{preview_mp3.sha256}"
                ),
                job_id=claimed.job_id,
                event_type="job.completed",
                artifact=audio_artifact,
                occurred_at=heartbeat_at,
            )
            persisted = await _apply_worker_event_fail_closed(
                event,
                uow=uow,
                media_result=media_result,
                artifact_root=settings.artifact_root,
            )
            return WorkerExecutionResult(
                job_id=claimed.job_id,
                status=persisted.status.value,
                artifact_id=persisted.artifact_id,
            )
        if claimed.job_type is MediaJobType.RENDER_CANONICAL:
            assert isinstance(media_result, CanonicalRenderResult)
            render_payload = _parse_canonical_render_payload(claimed)
            audio_artifact = AudioArtifact(
                artifact_id=uuid4(),
                project_id=claimed.project_id,
                revision_id=render_payload.revision_id,
                arrangement_hash=render_payload.arrangement_hash,
                render_scope=render_payload.render_scope,
                render_track_ids=render_payload.render_track_ids,
                source_job_id=claimed.job_id,
                content_hash=media_result.sha256,
                byte_size=media_result.byte_size,
                storage_key=media_result.storage_key,
                media_role=(
                    "canonical_master" if not render_payload.render_track_ids else "canonical_stem"
                ),
                quality_profile=render_payload.quality_profile,
                container="wav",
                codec="pcm",
                sample_rate_hz=media_result.sample_rate_hz,
                channels=media_result.channels,
                duration_seconds=media_result.duration_seconds,
                bit_depth=media_result.bit_depth,
                encoder="motif-forge-chromium-renderer",
                encoder_version=render_payload.audio_engine_version,
                lifecycle_class=ArtifactLifecycle.PROTECTED,
                protection_reasons=(f"revision:{render_payload.revision_id}",),
                created_at=heartbeat_at,
                last_accessed_at=heartbeat_at,
            )
            event = WorkerEvent(
                event_id=(
                    f"job:{claimed.job_id}:attempt:{claimed.attempts}:completed:"
                    f"{media_result.sha256}"
                ),
                job_id=claimed.job_id,
                event_type="job.completed",
                artifact=audio_artifact,
                occurred_at=heartbeat_at,
            )
            persisted = await _apply_worker_event_fail_closed(
                event,
                uow=uow,
                media_result=media_result,
                artifact_root=settings.artifact_root,
            )
            return WorkerExecutionResult(
                job_id=claimed.job_id,
                status=persisted.status.value,
                artifact_id=persisted.artifact_id,
            )
        if claimed.job_type is MediaJobType.EXPORT_BUNDLE:
            assert isinstance(media_result, tuple)
            _, bundle_artifact = media_result
            assert isinstance(bundle_artifact, ExportBundleArtifact)
            event = WorkerEvent(
                event_id=(
                    f"job:{claimed.job_id}:attempt:{claimed.attempts}:completed:"
                    f"{bundle_artifact.content_hash}"
                ),
                job_id=claimed.job_id,
                event_type="job.completed",
                artifact=bundle_artifact,
                occurred_at=heartbeat_at,
            )
            persisted = await _apply_worker_event_fail_closed(
                event,
                uow=uow,
                media_result=media_result,
                artifact_root=settings.artifact_root,
            )
            return WorkerExecutionResult(
                job_id=claimed.job_id,
                status=persisted.status.value,
                artifact_id=persisted.artifact_id,
            )
        if claimed.job_type is MediaJobType.TRANSCODE_EXPORT:
            assert isinstance(media_result, Mp3TranscodeResult)
            assert source is not None
            mp3_payload = _parse_export_mp3_payload(claimed)
            audio_artifact = AudioArtifact(
                artifact_id=uuid4(),
                project_id=claimed.project_id,
                revision_id=mp3_payload.revision_id,
                arrangement_hash=source.arrangement_hash,
                render_scope=RenderScope.MASTER,
                source_job_id=claimed.job_id,
                content_hash=media_result.sha256,
                byte_size=media_result.byte_size,
                storage_key=media_result.storage_key,
                media_role="delivery_master_mp3",
                quality_profile=MediaQualityProfile.DELIVERY_MP3_V1,
                container="mp3",
                codec="mp3",
                sample_rate_hz=media_result.sample_rate_hz,
                channels=media_result.channels,
                duration_seconds=media_result.duration_seconds,
                bitrate_kbps=media_result.bitrate_kbps,
                encoder="ffmpeg-libmp3lame",
                encoder_version="ffmpeg-system.v1",
                lifecycle_class=ArtifactLifecycle.PROTECTED,
                protection_reasons=(
                    f"revision:{mp3_payload.revision_id}",
                    f"source-artifact:{source.artifact_id}",
                ),
                created_at=heartbeat_at,
                last_accessed_at=heartbeat_at,
            )
            event = WorkerEvent(
                event_id=(
                    f"job:{claimed.job_id}:attempt:{claimed.attempts}:completed:"
                    f"{media_result.sha256}"
                ),
                job_id=claimed.job_id,
                event_type="job.completed",
                artifact=audio_artifact,
                occurred_at=heartbeat_at,
            )
            persisted = await _apply_worker_event_fail_closed(
                event,
                uow=uow,
                media_result=media_result,
                artifact_root=settings.artifact_root,
            )
            return WorkerExecutionResult(
                job_id=claimed.job_id,
                status=persisted.status.value,
                artifact_id=persisted.artifact_id,
            )
        if claimed.job_type is MediaJobType.REHYDRATE_FEATURE:
            assert isinstance(media_result, FeatureOutput)
            assert source is not None
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
            persisted = await _apply_worker_event_fail_closed(
                event,
                uow=uow,
                media_result=media_result,
                artifact_root=settings.artifact_root,
            )
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
            assert source is not None
            stretch_payload = _stretch_parameters(claimed)
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
                    "source_bpm": stretch_payload.source_bpm,
                    "target_bpm": stretch_payload.target_bpm,
                    "preserve_pitch": True,
                    "timeout_seconds": stretch_payload.timeout_seconds,
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
        persisted = await _apply_worker_event_fail_closed(
            event,
            uow=uow,
            media_result=media_result,
            artifact_root=settings.artifact_root,
        )
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
        MediaJobType.TRANSCODE_EXPORT,
    }:
        raise TimeStretchError(
            "MEDIA_JOB_TYPE_UNSUPPORTED", "This Worker does not support the requested Job type."
        )
    if job.job_type is MediaJobType.TRANSCODE_EXPORT:
        expected_profile = job.output_quality_profile is MediaQualityProfile.DELIVERY_MP3_V1
    else:
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
            _parse_export_mp3_payload(job).source_artifact_id
            if job.job_type is MediaJobType.TRANSCODE_EXPORT
            else _stretch_source_artifact_id(job)
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
        raise AudioIngestError("ARTIFACT_REHYDRATION_CHECKSUM_MISMATCH", "Feature checksum changed")
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


def _parse_canonical_render_payload(job: MediaJob) -> CanonicalRenderJobPayload:
    return CanonicalRenderJobPayload.model_validate_json(json.dumps(job.input_payload), strict=True)


def _parse_candidate_preview_payload(job: MediaJob) -> CandidatePreviewJobPayload:
    return CandidatePreviewJobPayload.model_validate_json(
        json.dumps(job.input_payload), strict=True
    )


def _parse_export_mp3_payload(job: MediaJob) -> ExportMp3JobPayload:
    return ExportMp3JobPayload.model_validate_json(json.dumps(job.input_payload), strict=True)


def _parse_export_bundle_payload(job: MediaJob) -> ExportBundleJobPayload:
    return ExportBundleJobPayload.model_validate_json(json.dumps(job.input_payload), strict=True)


async def _execute_export_bundle(
    job: MediaJob,
    uow: PostgresMediaJobUnitOfWork,
    settings: Settings,
    *,
    cancel_event: threading.Event | None = None,
) -> tuple[ExportBundleJobPayload, ExportBundleArtifact]:
    payload = _parse_export_bundle_payload(job)
    if (
        payload.project_id != job.project_id
        or job.output_quality_profile is not MediaQualityProfile.EXPORT_BUNDLE_V1
    ):
        raise ExportTranscodeError("EXPORT_BUNDLE_JOB_LINEAGE_INVALID")
    async with uow() as transaction:
        revision = await transaction.get_revision(payload.revision_id)
        if (
            revision is None
            or revision.project_id != job.project_id
            or revision.content_hash != payload.arrangement_hash
        ):
            raise ExportTranscodeError("EXPORT_BUNDLE_REVISION_UNAVAILABLE")
        resolved: list[tuple[BundleAudioInput, AudioArtifact]] = []
        for item in payload.audio_inputs:
            audio_artifact = await transaction.get_audio_artifact(item.artifact_id)
            if (
                audio_artifact is None
                or audio_artifact.project_id != job.project_id
                or audio_artifact.content_hash != item.content_hash
                or audio_artifact.quality_profile is not item.quality_profile
                or audio_artifact.availability is not ArtifactAvailability.AVAILABLE
                or audio_artifact.revision_id != payload.revision_id
                or audio_artifact.arrangement_hash != payload.arrangement_hash
            ):
                raise ExportTranscodeError("EXPORT_BUNDLE_INPUT_UNAVAILABLE")
            resolved.append((item, audio_artifact))
    request = ExportBundleRequest(
        project_id=job.project_id,
        revision_id=payload.revision_id,
        seed=payload.seed,
        arrangement=revision.arrangement_ir,
        arrangement_hash=payload.arrangement_hash,
        audio_exports=tuple(
            AudioExportRef(
                artifact_id=artifact.artifact_id,
                quality_profile=artifact.quality_profile,
                storage_key=artifact.storage_key,
                sha256=artifact.content_hash,
                byte_size=artifact.byte_size,
                filename=item.filename,
            )
            for item, artifact in resolved
        ),
        engine_version=payload.engine_version,
        trace_refs=payload.trace_refs,
    )
    result = await asyncio.to_thread(
        write_export_bundle,
        artifact_root=settings.artifact_root,
        request=request,
        cancel_event=cancel_event,
    )
    bundle_artifact = ExportBundleArtifact(
        artifact_id=uuid4(),
        project_id=job.project_id,
        source_job_id=job.job_id,
        revision_id=payload.revision_id,
        content_hash=result.manifest_sha256,
        byte_size=result.total_bytes,
        storage_prefix=result.storage_prefix,
        file_count=result.file_count,
        arrangement_hash=payload.arrangement_hash,
        engine_version=payload.engine_version,
        seed=payload.seed,
        input_artifact_ids=tuple(item.artifact_id for item in payload.audio_inputs),
        created_new=result.created_new,
        created_at=datetime.now(UTC),
    )
    return payload, bundle_artifact


async def _execute_export_transcode(
    job: MediaJob,
    source: AudioArtifact,
    settings: Settings,
    *,
    cancel_event: threading.Event | None = None,
) -> Mp3TranscodeResult:
    payload = _parse_export_mp3_payload(job)
    if (
        payload.project_id != job.project_id
        or payload.source_artifact_id != source.artifact_id
        or payload.source_content_hash != source.content_hash
        or source.quality_profile is not MediaQualityProfile.CANONICAL_MASTER_V1
        or source.revision_id != payload.revision_id
        or source.render_scope is not RenderScope.MASTER
        or source.arrangement_hash is None
    ):
        raise ExportTranscodeError("TRANSCODE_JOB_LINEAGE_INVALID")
    return await asyncio.to_thread(
        transcode_master_to_mp3,
        artifact_root=settings.artifact_root,
        temp_root=settings.temp_root,
        job_id=job.job_id,
        project_id=job.project_id,
        revision_id=payload.revision_id,
        source_storage_key=source.storage_key,
        expected_duration_seconds=source.duration_seconds or 0.0,
        timeout_seconds=payload.timeout_seconds,
        cancel_event=cancel_event,
    )


async def _execute_canonical_render(
    job: MediaJob, uow: PostgresMediaJobUnitOfWork, settings: Settings
) -> CanonicalRenderResult:
    payload = _parse_canonical_render_payload(job)
    if (
        payload.project_id != job.project_id
        or payload.quality_profile != job.output_quality_profile
    ):
        raise ChromiumRenderError("RENDER_JOB_LINEAGE_INVALID")
    async with uow() as transaction:
        revision = await transaction.get_revision(payload.revision_id)
    if revision is None or revision.project_id != job.project_id:
        raise ChromiumRenderError("RENDER_REVISION_UNAVAILABLE")
    projection = compile_audio_graph(
        revision.arrangement_ir,
        render_track_ids=(
            None if payload.render_scope is RenderScope.MASTER else payload.render_track_ids
        ),
    )
    if (
        revision.content_hash != payload.arrangement_hash
        or projection.arrangement_hash != payload.arrangement_hash
        or projection.graph_hash != payload.audio_graph_hash
        or projection.graph != payload.audio_graph
    ):
        raise ChromiumRenderError("RENDER_REVISION_GRAPH_MISMATCH")
    return await ChromiumRenderClient(
        artifact_root=settings.artifact_root,
        temp_root=settings.temp_root,
        service_url=settings.render_service_url,
    ).render(job_id=job.job_id, payload=payload)


async def _execute_candidate_preview(
    job: MediaJob,
    uow: PostgresMediaJobUnitOfWork,
    settings: Settings,
    *,
    cancel_event: threading.Event | None = None,
) -> tuple[CandidatePreviewJobPayload, Mp3TranscodeResult]:
    payload = _parse_candidate_preview_payload(job)
    if (
        payload.project_id != job.project_id
        or job.output_quality_profile is not MediaQualityProfile.CANDIDATE_PREVIEW_V1
    ):
        raise ChromiumRenderError("CANDIDATE_PREVIEW_LINEAGE_MISMATCH")
    async with uow() as transaction:
        snapshot = await transaction.get_candidate_snapshot(payload.candidate_snapshot_id)
    if snapshot is None:
        raise ChromiumRenderError("CANDIDATE_PREVIEW_SNAPSHOT_UNAVAILABLE")
    validate_candidate_preview_lineage(payload, snapshot)
    rendered = await ChromiumRenderClient(
        artifact_root=settings.artifact_root,
        temp_root=settings.temp_root,
        service_url=settings.render_service_url,
    ).render(job_id=job.job_id, payload=payload)
    try:
        mp3 = await asyncio.to_thread(
            transcode_master_to_mp3,
            artifact_root=settings.artifact_root,
            temp_root=settings.temp_root,
            job_id=job.job_id,
            project_id=job.project_id,
            candidate_snapshot_id=payload.candidate_snapshot_id,
            source_storage_key=rendered.storage_key,
            expected_duration_seconds=rendered.duration_seconds,
            timeout_seconds=payload.timeout_seconds,
            bitrate_kbps=payload.bitrate_kbps,
            cancel_event=cancel_event,
        )
        if (
            payload.expected_output_content_hash is not None
            and mp3.sha256 != payload.expected_output_content_hash
        ):
            _discard_candidate_preview_output(mp3, artifact_root=settings.artifact_root)
            raise ExportTranscodeError("ARTIFACT_REHYDRATION_CHECKSUM_MISMATCH")
        if payload.expected_recipe_hash is not None:
            recipe = _candidate_preview_rebuild_recipe(payload)
            if recipe.content_hash != payload.expected_recipe_hash:
                _discard_candidate_preview_output(mp3, artifact_root=settings.artifact_root)
                raise ExportTranscodeError("ARTIFACT_REHYDRATION_RECIPE_MISMATCH")
    finally:
        root = settings.artifact_root.resolve()
        temporary_wav = (root / rendered.storage_key).resolve()
        if temporary_wav.is_relative_to(root):
            temporary_wav.unlink(missing_ok=True)
    return payload, mp3


def _discard_candidate_preview_output(
    result: Mp3TranscodeResult, *, artifact_root: Path
) -> None:
    if not result.created_new:
        return
    root = artifact_root.resolve()
    output = (root / result.storage_key).resolve()
    if output.is_relative_to(root):
        output.unlink(missing_ok=True)


async def _run_artifact_storage_gate(
    job: MediaJob,
    settings: Settings,
    media_uow: PostgresMediaJobUnitOfWork,
) -> str | None:
    if job.job_type not in {
        MediaJobType.RENDER_PREVIEW,
        MediaJobType.RENDER_CANONICAL,
        MediaJobType.TRANSCODE_EXPORT,
        MediaJobType.EXPORT_BUNDLE,
    }:
        return None
    session_factory = media_uow.session_factory
    storage_uow = PostgresStorageUnitOfWork(session_factory)
    dependency_ids: tuple[UUID, ...] = ()
    if job.job_type is MediaJobType.RENDER_PREVIEW:
        payload_preview = _parse_candidate_preview_payload(job)
        artifact_bytes = payload_preview.maximum_output_bytes
        temp_bytes = payload_preview.maximum_output_bytes
    elif job.job_type is MediaJobType.RENDER_CANONICAL:
        payload = _parse_canonical_render_payload(job)
        artifact_bytes = payload.maximum_output_bytes
        temp_bytes = payload.maximum_output_bytes
    elif job.job_type is MediaJobType.TRANSCODE_EXPORT:
        payload_mp3 = _parse_export_mp3_payload(job)
        dependency_ids = (payload_mp3.source_artifact_id,)
        artifact_bytes = 32 * 1024 * 1024
        temp_bytes = 32 * 1024 * 1024
    else:
        payload_bundle = _parse_export_bundle_payload(job)
        dependency_ids = tuple(item.artifact_id for item in payload_bundle.audio_inputs)
        async with media_uow() as transaction:
            inputs = [await transaction.get_audio_artifact(item) for item in dependency_ids]
        if any(item is None for item in inputs):
            return "EXPORT_BUNDLE_INPUT_UNAVAILABLE"
        artifact_bytes = 8 * 1024 * 1024
        temp_bytes = 8 * 1024 * 1024
    gate = RunStoragePressureGate(
        inspect_root=LocalStorageRootInspector(settings.artifact_root),
        load_facts=PostgresStorageFactsLoader(storage_uow, temp_root=settings.temp_root),
        collector=LocalArtifactCollector(storage_uow, artifact_root=settings.artifact_root),
        record_event=PersistentStorageEventRecorder(storage_uow),
        global_quota_bytes=settings.artifact_global_quota_bytes,
        project_quota_bytes=settings.artifact_project_quota_bytes,
        temp_quota_bytes=settings.temp_quota_bytes,
        minimum_free_bytes=settings.storage_min_free_bytes,
    )
    decision = await gate(
        operation_id=f"media-job:{job.job_id}:attempt:{job.attempts}",
        project_id=job.project_id,
        estimated_artifact_bytes=artifact_bytes,
        estimated_temp_bytes=temp_bytes,
        dependency_artifact_ids=dependency_ids,
    )
    if decision.route is StorageRoute.PROCEED:
        return None
    return decision.error_code or "STORAGE_PRESSURE_BLOCKED"


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
