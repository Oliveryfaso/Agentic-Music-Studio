from __future__ import annotations

import asyncio
import hashlib
import math
import os
import struct
import wave
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config
from motif_forge.agent.planner import PlannerResponse, PlannerUsage
from motif_forge.application.errors import ChangeImpactEscalatedError, RevisionConflictError
from motif_forge.application.media_jobs import (
    ApplyWorkerEvent,
    EnqueueMediaJob,
    EnqueueMediaJobRequest,
    StartArtifactRehydration,
    StartArtifactRehydrationRequest,
)
from motif_forge.application.previews import (
    CreateCommandPreview,
    CreateCommandPreviewRequest,
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.application.storage import LocalArtifactCollector
from motif_forge.config import Settings
from motif_forge.domain.commands import AddTrackCommand, AddTrackPayload
from motif_forge.domain.ir import Track, TrackRole, TrackType
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    JobStatus,
    MediaJobType,
    MediaQualityProfile,
    TimeStretchJobPayload,
    WorkerEvent,
)
from motif_forge.domain.revisions import AuthorKind, ChangeImpact
from motif_forge.infrastructure.observability import PostgresTelemetryRecorder
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork
from motif_forge.infrastructure.persistence.tables import (
    ApprovalRow,
    AudioArtifactRow,
    AuditEventRow,
    BranchRow,
    CandidateSnapshotRow,
    CommandBatchRow,
    FeatureArtifactRow,
    IdempotencyRow,
    InboxReceiptRow,
    JobEventRow,
    MediaJobRow,
    MediaRunRow,
    OutboxEventRow,
    PreviewCandidateRow,
    ProjectRow,
    RevisionCommandRow,
    RevisionRow,
    RunEventRow,
    StorageEventRow,
    TraceRow,
    TraceSpanRow,
    UploadPartRow,
    UploadSessionRow,
    UsageLedgerRow,
)
from motif_forge.observability.models import ModelCallRecord
from motif_forge.worker.celery_app import create_celery_app
from motif_forge.worker.execution import execute_media_job
from motif_forge.worker.outbox import CeleryMediaJobPublisher, PostgresOutboxStore, dispatch_once
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine


def _upgrade_database(dsn: str) -> None:
    project_root = Path(__file__).resolve().parents[4]
    config = Config(project_root / "alembic.ini")
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        alembic_command.upgrade(config, "head")


@pytest_asyncio.fixture
async def persistence_engine(test_postgres_dsn: str) -> AsyncIterator[AsyncEngine]:
    """Upgrade and connect only to the explicitly opted-in PostgreSQL test database."""

    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


def _add_track(
    actor_kind: Literal["human", "agent", "system"] = "human",
) -> AddTrackCommand:
    return AddTrackCommand(
        command_id=uuid4(),
        actor_kind=actor_kind,
        client_sequence=0,
        payload=AddTrackPayload(
            track=Track(
                track_id=uuid4(),
                track_type=TrackType.INSTRUMENT,
                name="Integration Keys",
                role=TrackRole.HARMONY,
                instrument_ref="builtin:piano",
            )
        ),
    )


async def _delete_exact_project(engine: AsyncEngine, project_id: UUID) -> None:
    """Remove only rows reachable from the one project created by this test."""

    revision_ids = select(RevisionRow.id).where(RevisionRow.project_id == project_id)
    async with engine.begin() as connection:
        # The project/root Revision/main Branch form intentional deferred FK cycles.
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        run_ids = select(MediaRunRow.id).where(MediaRunRow.project_id == project_id)
        job_ids = select(MediaJobRow.id).where(MediaJobRow.project_id == project_id)
        external_event_ids = select(JobEventRow.external_event_id).where(
            JobEventRow.job_id.in_(job_ids), JobEventRow.external_event_id.is_not(None)
        )
        await connection.execute(
            delete(FeatureArtifactRow).where(FeatureArtifactRow.project_id == project_id)
        )
        await connection.execute(
            delete(AudioArtifactRow).where(AudioArtifactRow.project_id == project_id)
        )
        upload_ids = select(UploadSessionRow.id).where(UploadSessionRow.project_id == project_id)
        await connection.execute(
            delete(UploadPartRow).where(UploadPartRow.upload_id.in_(upload_ids))
        )
        await connection.execute(
            delete(UploadSessionRow).where(UploadSessionRow.project_id == project_id)
        )
        await connection.execute(
            delete(InboxReceiptRow).where(InboxReceiptRow.event_id.in_(external_event_ids))
        )
        await connection.execute(
            delete(OutboxEventRow).where(
                (OutboxEventRow.aggregate_id.in_(run_ids))
                | (OutboxEventRow.aggregate_id.in_(job_ids))
            )
        )
        await connection.execute(delete(JobEventRow).where(JobEventRow.job_id.in_(job_ids)))
        await connection.execute(delete(RunEventRow).where(RunEventRow.run_id.in_(run_ids)))
        await connection.execute(delete(MediaJobRow).where(MediaJobRow.project_id == project_id))
        await connection.execute(delete(MediaRunRow).where(MediaRunRow.project_id == project_id))
        await connection.execute(
            delete(AuditEventRow).where(AuditEventRow.project_id == project_id)
        )
        await connection.execute(
            delete(StorageEventRow).where(StorageEventRow.project_id == project_id)
        )
        await connection.execute(delete(ApprovalRow).where(ApprovalRow.project_id == project_id))
        await connection.execute(
            delete(PreviewCandidateRow).where(PreviewCandidateRow.project_id == project_id)
        )
        await connection.execute(
            delete(CandidateSnapshotRow).where(CandidateSnapshotRow.project_id == project_id)
        )
        await connection.execute(
            delete(RevisionCommandRow).where(RevisionCommandRow.revision_id.in_(revision_ids))
        )
        await connection.execute(
            delete(IdempotencyRow).where(
                IdempotencyRow.resource_id.in_(
                    select(RevisionRow.id).where(RevisionRow.project_id == project_id)
                )
                | (IdempotencyRow.resource_id == project_id)
            )
        )
        await connection.execute(
            delete(CommandBatchRow).where(CommandBatchRow.project_id == project_id)
        )
        await connection.execute(delete(BranchRow).where(BranchRow.project_id == project_id))
        await connection.execute(delete(RevisionRow).where(RevisionRow.project_id == project_id))
        await connection.execute(delete(ProjectRow).where(ProjectRow.id == project_id))


def _write_pcm16_stereo_sine(path: Path, *, seconds: float = 2.0) -> None:
    sample_rate = 48_000
    frame_count = round(sample_rate * seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for frame in range(frame_count):
            envelope = min(1.0, frame / 240) * min(1.0, (frame_count - frame) / 240)
            sample = int(math.sin(2 * math.pi * 440 * frame / sample_rate) * envelope * 12_000)
            frames.extend(struct.pack("<hh", sample, sample))
        output.writeframes(frames)


@pytest.mark.asyncio
async def test_media_job_outbox_and_worker_completion_are_idempotent_in_real_postgres(
    persistence_engine: AsyncEngine,
) -> None:
    session_factory = create_session_factory(persistence_engine)
    project_uow = PostgresUnitOfWork(session_factory)
    media_uow = PostgresMediaJobUnitOfWork(session_factory)
    created = await CreateProject(project_uow)(
        CreateProjectRequest(
            name="PostgreSQL Media Job Project",
            actor_id="integration-test",
            idempotency_key=f"create-{uuid4().hex}",
        )
    )
    try:
        request = EnqueueMediaJobRequest(
            project_id=created.project_id,
            thread_id=f"thread-{uuid4().hex}",
            run_type="candidate_preview",
            job_type=MediaJobType.RENDER_PREVIEW,
            input_payload={"candidate_snapshot_id": str(uuid4())},
            output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
            idempotency_key=f"render-{uuid4().hex}",
        )
        queued = await EnqueueMediaJob(media_uow)(request)
        replayed_queue = await EnqueueMediaJob(media_uow)(request)
        assert replayed_queue.job_id == queued.job_id
        assert replayed_queue.replayed is True

        now = datetime.now(UTC)
        artifact = AudioArtifact(
            artifact_id=uuid4(),
            project_id=created.project_id,
            source_job_id=queued.job_id,
            content_hash="c" * 64,
            byte_size=4096,
            storage_key="sha256/cc/candidate-preview.mp3",
            media_role="candidate_preview",
            quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
            container="mp3",
            codec="mp3",
            sample_rate_hz=48_000,
            channels=2,
            duration_seconds=30.0,
            bitrate_kbps=160,
            encoder="ffmpeg",
            encoder_version="7.1",
            lifecycle_class=ArtifactLifecycle.PROTECTED,
            created_at=now,
        )
        event = WorkerEvent(
            event_id=f"worker-{uuid4().hex}",
            job_id=queued.job_id,
            event_type="job.completed",
            artifact=artifact,
            occurred_at=now,
        )
        completed = await ApplyWorkerEvent(media_uow)(event)
        replayed_completion = await ApplyWorkerEvent(media_uow)(event)

        assert completed.status is JobStatus.SUCCEEDED
        assert completed.artifact_id == artifact.artifact_id
        assert replayed_completion.replayed is True

        async with persistence_engine.connect() as connection:
            job_count = await connection.scalar(
                select(func.count())
                .select_from(MediaJobRow)
                .where(MediaJobRow.project_id == created.project_id)
            )
            artifact_count = await connection.scalar(
                select(func.count())
                .select_from(AudioArtifactRow)
                .where(AudioArtifactRow.project_id == created.project_id)
            )
            completion_event_count = await connection.scalar(
                select(func.count())
                .select_from(JobEventRow)
                .where(
                    JobEventRow.job_id == queued.job_id,
                    JobEventRow.event_type == "job.completed",
                )
            )
            resume_outbox_count = await connection.scalar(
                select(func.count())
                .select_from(OutboxEventRow)
                .where(
                    OutboxEventRow.aggregate_id == queued.run_id,
                    OutboxEventRow.topic == "graph.resume.requested",
                )
            )

        assert job_count == 1
        assert artifact_count == 1
        assert completion_event_count == 1
        assert resume_outbox_count == 1
    finally:
        await _delete_exact_project(persistence_engine, created.project_id)


@pytest.mark.asyncio
async def test_persisted_time_stretch_job_executes_and_duplicate_delivery_is_safe(
    persistence_engine: AsyncEngine,
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    session_factory = create_session_factory(persistence_engine)
    project_uow = PostgresUnitOfWork(session_factory)
    media_uow = PostgresMediaJobUnitOfWork(session_factory)
    created = await CreateProject(project_uow)(
        CreateProjectRequest(
            name="PostgreSQL Time Stretch Project",
            actor_id="integration-test",
            idempotency_key=f"create-{uuid4().hex}",
        )
    )
    artifact_root = tmp_path / "artifacts"
    source_artifact_id = uuid4()
    source_storage_key = f"protected/{source_artifact_id}.wav"
    source_path = artifact_root / source_storage_key
    _write_pcm16_stereo_sine(source_path)
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    try:
        seed = await EnqueueMediaJob(media_uow)(
            EnqueueMediaJobRequest(
                project_id=created.project_id,
                thread_id=f"thread-{uuid4().hex}",
                run_type="normalize_import",
                job_type=MediaJobType.INGEST,
                input_payload={"source": "integration-fixture"},
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=f"normalize-{uuid4().hex}",
            )
        )
        source_artifact = AudioArtifact(
            artifact_id=source_artifact_id,
            project_id=created.project_id,
            source_job_id=seed.job_id,
            content_hash=source_hash,
            byte_size=source_path.stat().st_size,
            storage_key=source_storage_key,
            media_role="normalized_import",
            quality_profile=MediaQualityProfile.WORKING_PCM_V1,
            container="wav",
            codec="pcm",
            sample_rate_hz=48_000,
            channels=2,
            duration_seconds=2.0,
            bit_depth=16,
            encoder="integration-fixture",
            encoder_version="1",
            lifecycle_class=ArtifactLifecycle.PROTECTED,
            created_at=datetime.now(UTC),
        )
        await ApplyWorkerEvent(media_uow)(
            WorkerEvent(
                event_id=f"seed-{uuid4().hex}",
                job_id=seed.job_id,
                event_type="job.completed",
                artifact=source_artifact,
                occurred_at=datetime.now(UTC),
            )
        )
        payload = TimeStretchJobPayload(
            source_artifact_id=source_artifact_id,
            source_bpm=120,
            target_bpm=96,
        )
        queued = await EnqueueMediaJob(media_uow)(
            EnqueueMediaJobRequest(
                project_id=created.project_id,
                thread_id=f"thread-{uuid4().hex}",
                run_type="time_stretch",
                job_type=MediaJobType.TIME_STRETCH,
                input_payload=payload.model_dump(mode="json"),
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=f"stretch-{uuid4().hex}",
            )
        )
        settings = Settings(
            environment="test",
            postgres_dsn=test_postgres_dsn,
            storage_profile="lean",
            artifact_root=artifact_root,
            temp_root=artifact_root / "tmp",
        )

        completed = await execute_media_job(
            queued.job_id, settings=settings, worker_id="integration-worker"
        )
        replayed = await execute_media_job(
            queued.job_id, settings=settings, worker_id="duplicate-delivery"
        )

        assert completed.status == JobStatus.SUCCEEDED.value
        assert completed.artifact_id is not None
        assert replayed.status == JobStatus.SUCCEEDED.value
        assert replayed.artifact_id == completed.artifact_id
        async with persistence_engine.connect() as connection:
            artifact_count = await connection.scalar(
                select(func.count())
                .select_from(AudioArtifactRow)
                .where(AudioArtifactRow.project_id == created.project_id)
            )
            attempt_count = await connection.scalar(
                select(MediaJobRow.attempts).where(MediaJobRow.id == queued.job_id)
            )
            output_key = await connection.scalar(
                select(AudioArtifactRow.storage_key).where(
                    AudioArtifactRow.id == completed.artifact_id
                )
            )
        assert artifact_count == 2
        assert attempt_count == 1
        assert output_key is not None
        assert (artifact_root / output_key).is_file()
    finally:
        await _delete_exact_project(persistence_engine, created.project_id)


@pytest.mark.asyncio
async def test_celery_dispatcher_and_media_worker_execute_time_stretch_end_to_end(
    persistence_engine: AsyncEngine,
    test_postgres_dsn: str,
) -> None:
    redis_url = os.environ.get("MOTIF_FORGE_TEST_REDIS_URL", "").strip()
    artifact_root_value = os.environ.get("MOTIF_FORGE_TEST_ARTIFACT_ROOT", "").strip()
    if not redis_url or not artifact_root_value:
        pytest.skip(
            "real Celery E2E requires MOTIF_FORGE_TEST_REDIS_URL and MOTIF_FORGE_TEST_ARTIFACT_ROOT"
        )
    artifact_root = Path(artifact_root_value).resolve()
    session_factory = create_session_factory(persistence_engine)
    project_uow = PostgresUnitOfWork(session_factory)
    media_uow = PostgresMediaJobUnitOfWork(session_factory)
    created = await CreateProject(project_uow)(
        CreateProjectRequest(
            name="Celery Time Stretch E2E",
            actor_id="integration-test",
            idempotency_key=f"create-{uuid4().hex}",
        )
    )
    source_artifact_id = uuid4()
    source_storage_key = f"protected/{source_artifact_id}.wav"
    source_path = artifact_root / source_storage_key
    output_path: Path | None = None
    _write_pcm16_stereo_sine(source_path)
    try:
        seed = await EnqueueMediaJob(media_uow)(
            EnqueueMediaJobRequest(
                project_id=created.project_id,
                thread_id=f"thread-{uuid4().hex}",
                run_type="normalize_import",
                job_type=MediaJobType.INGEST,
                input_payload={"source": "celery-e2e-fixture"},
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=f"normalize-{uuid4().hex}",
            )
        )
        await ApplyWorkerEvent(media_uow)(
            WorkerEvent(
                event_id=f"seed-{uuid4().hex}",
                job_id=seed.job_id,
                event_type="job.completed",
                artifact=AudioArtifact(
                    artifact_id=source_artifact_id,
                    project_id=created.project_id,
                    source_job_id=seed.job_id,
                    content_hash=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                    byte_size=source_path.stat().st_size,
                    storage_key=source_storage_key,
                    media_role="normalized_import",
                    quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                    container="wav",
                    codec="pcm",
                    sample_rate_hz=48_000,
                    channels=2,
                    duration_seconds=2.0,
                    bit_depth=16,
                    encoder="integration-fixture",
                    encoder_version="1",
                    lifecycle_class=ArtifactLifecycle.PROTECTED,
                    created_at=datetime.now(UTC),
                ),
                occurred_at=datetime.now(UTC),
            )
        )
        async with persistence_engine.begin() as connection:
            await connection.execute(
                update(OutboxEventRow)
                .where(
                    OutboxEventRow.aggregate_id == seed.job_id,
                    OutboxEventRow.topic == "media.job.dispatch.requested",
                )
                .values(status="published", published_at=datetime.now(UTC))
            )
        queued = await EnqueueMediaJob(media_uow)(
            EnqueueMediaJobRequest(
                project_id=created.project_id,
                thread_id=f"thread-{uuid4().hex}",
                run_type="time_stretch",
                job_type=MediaJobType.TIME_STRETCH,
                input_payload=TimeStretchJobPayload(
                    source_artifact_id=source_artifact_id,
                    source_bpm=120,
                    target_bpm=96,
                ).model_dump(mode="json"),
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=f"stretch-{uuid4().hex}",
            )
        )
        settings = Settings(
            environment="test",
            postgres_dsn=test_postgres_dsn,
            redis_url=redis_url,
            storage_profile="lean",
            artifact_root=artifact_root,
            temp_root=artifact_root / "tmp",
        )
        celery_app = create_celery_app(settings)
        claimed = await dispatch_once(
            PostgresOutboxStore(session_factory),
            CeleryMediaJobPublisher(celery_app, queue=settings.media_worker_queue),
            owner=f"integration-dispatcher-{uuid4().hex}",
            batch_size=16,
            lease_seconds=60,
        )
        assert claimed in {0, 1}  # A concurrently running dispatcher may win the lease.

        deadline = asyncio.get_running_loop().time() + 20
        status = "queued"
        result_artifact_id: UUID | None = None
        while asyncio.get_running_loop().time() < deadline:
            async with persistence_engine.connect() as connection:
                row = (
                    await connection.execute(
                        select(MediaJobRow.status, MediaJobRow.result_artifact_id).where(
                            MediaJobRow.id == queued.job_id
                        )
                    )
                ).one()
                status = row.status
                result_artifact_id = row.result_artifact_id
            if status in {JobStatus.SUCCEEDED.value, JobStatus.FAILED_TERMINAL.value}:
                break
            await asyncio.sleep(0.25)
        assert status == JobStatus.SUCCEEDED.value
        assert result_artifact_id is not None
        async with persistence_engine.connect() as connection:
            output_key = await connection.scalar(
                select(AudioArtifactRow.storage_key).where(
                    AudioArtifactRow.id == result_artifact_id
                )
            )
            attempts_before_duplicate = await connection.scalar(
                select(MediaJobRow.attempts).where(MediaJobRow.id == queued.job_id)
            )
        assert output_key is not None
        output_path = artifact_root / output_key
        assert output_path.is_file()

        celery_app.send_task(
            "motif_forge.execute_media_job",
            args=[str(queued.job_id)],
            queue=settings.media_worker_queue,
            task_id=str(uuid4()),
        )
        await asyncio.sleep(1.0)
        async with persistence_engine.connect() as connection:
            attempts_after_duplicate = await connection.scalar(
                select(MediaJobRow.attempts).where(MediaJobRow.id == queued.job_id)
            )
        assert attempts_before_duplicate == attempts_after_duplicate == 1

        reclaimed = await LocalArtifactCollector(
            PostgresStorageUnitOfWork(session_factory), artifact_root=artifact_root
        )(
            operation_id=f"e2e-evict-{result_artifact_id}",
            artifact_ids=(result_artifact_id,),
        )
        assert reclaimed > 0
        assert not output_path.exists()
        rehydration = await StartArtifactRehydration(media_uow)(
            StartArtifactRehydrationRequest(
                project_id=created.project_id,
                artifact_id=result_artifact_id,
                thread_id=f"rehydrate-{uuid4().hex}",
                idempotency_key=f"rehydrate-{result_artifact_id}",
            )
        )
        claimed = await dispatch_once(
            PostgresOutboxStore(session_factory),
            CeleryMediaJobPublisher(celery_app, queue=settings.media_worker_queue),
            owner=f"rehydration-dispatcher-{uuid4().hex}",
            batch_size=16,
            lease_seconds=60,
        )
        assert claimed in {0, 1}
        deadline = asyncio.get_running_loop().time() + 20
        rehydration_status = "queued"
        while asyncio.get_running_loop().time() < deadline:
            async with persistence_engine.connect() as connection:
                row = (
                    await connection.execute(
                        select(
                            MediaJobRow.status,
                            MediaJobRow.result_artifact_id,
                            AudioArtifactRow.availability,
                        )
                        .join(
                            AudioArtifactRow,
                            AudioArtifactRow.id == result_artifact_id,
                        )
                        .where(MediaJobRow.id == rehydration.job_id)
                    )
                ).one()
                rehydration_status = row.status
                assert row.result_artifact_id in {None, result_artifact_id}
                availability = row.availability
            if rehydration_status in {
                JobStatus.SUCCEEDED.value,
                JobStatus.FAILED_TERMINAL.value,
            }:
                break
            await asyncio.sleep(0.25)
        assert rehydration_status == JobStatus.SUCCEEDED.value
        assert availability == "available"
        assert output_path.is_file()
    finally:
        await _delete_exact_project(persistence_engine, created.project_id)
        if source_path.is_file():
            source_path.unlink()
        if output_path is not None and output_path.is_file():
            output_path.unlink()


@pytest.mark.asyncio
async def test_root_commit_idempotency_and_stale_head_conflict_use_real_postgres(
    persistence_engine: AsyncEngine,
) -> None:
    """Exercise transaction commit, replay, and optimistic conflict against PostgreSQL."""

    uow = PostgresUnitOfWork(create_session_factory(persistence_engine))
    create_request = CreateProjectRequest(
        name="PostgreSQL Integration Project",
        actor_id="integration-test",
        idempotency_key=f"create-{uuid4().hex}",
    )

    created = await CreateProject(uow)(create_request)
    try:
        replayed_create = await CreateProject(uow)(create_request)
        assert replayed_create.project_id == created.project_id
        assert replayed_create.root_revision_id == created.root_revision_id
        assert replayed_create.replayed is True

        commit_request = CommitCommandBatchRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=created.root_revision_id,
            commands=(_add_track(),),
            actor_id="integration-test",
            author_kind=AuthorKind.HUMAN,
            reason="TRACK_ADDED",
            idempotency_key=f"commit-{uuid4().hex}",
        )
        commit_use_case = CommitCommandBatch(uow)
        committed = await commit_use_case(commit_request)
        replayed_commit = await commit_use_case(commit_request)

        assert committed.actual_change_impact is ChangeImpact.L1
        assert replayed_commit.revision_id == committed.revision_id
        assert replayed_commit.replayed is True

        stale_request = CommitCommandBatchRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=created.root_revision_id,
            commands=(_add_track(),),
            actor_id="integration-test",
            author_kind=AuthorKind.HUMAN,
            reason="STALE_TRACK_ADDED",
            idempotency_key=f"stale-{uuid4().hex}",
        )
        with pytest.raises(RevisionConflictError) as raised:
            await commit_use_case(stale_request)

        assert raised.value.code == "REVISION_CONFLICT"
        assert raised.value.current_revision_id == committed.revision_id

        l2_request = CommitCommandBatchRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=committed.revision_id,
            commands=(_add_track("agent"),),
            actor_id="integration-planner",
            author_kind=AuthorKind.AGENT,
            reason="AI_TRACK_ADDED",
            idempotency_key=f"l2-{uuid4().hex}",
        )
        with pytest.raises(ChangeImpactEscalatedError) as escalated:
            await commit_use_case(l2_request)

        assert escalated.value.code == "CHANGE_IMPACT_ESCALATED"

        async with persistence_engine.connect() as connection:
            branch_head = await connection.scalar(
                select(BranchRow.head_revision_id).where(BranchRow.id == created.active_branch_id)
            )
            revision_count = await connection.scalar(
                select(func.count())
                .select_from(RevisionRow)
                .where(RevisionRow.project_id == created.project_id)
            )
            command_count = await connection.scalar(
                select(func.count())
                .select_from(RevisionCommandRow)
                .where(RevisionCommandRow.revision_id == committed.revision_id)
            )

        assert branch_head == committed.revision_id
        assert revision_count == 2
        assert command_count == 1
    finally:
        await _delete_exact_project(persistence_engine, created.project_id)


@pytest.mark.asyncio
async def test_candidate_preview_approval_materializes_once_in_real_postgres(
    persistence_engine: AsyncEngine,
) -> None:
    uow = PostgresUnitOfWork(create_session_factory(persistence_engine))
    created = await CreateProject(uow)(
        CreateProjectRequest(
            name="PostgreSQL Preview Project",
            actor_id="integration-test",
            idempotency_key=f"create-{uuid4().hex}",
        )
    )
    try:
        preview_request = CreateCommandPreviewRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=created.root_revision_id,
            candidate_id=uuid4(),
            commands=(_add_track("agent"),),
            actor_id="integration-planner",
            idempotency_key=f"preview-{uuid4().hex}",
        )
        preview = await CreateCommandPreview(uow)(preview_request)
        replayed_preview = await CreateCommandPreview(uow)(preview_request)

        assert replayed_preview.preview_id == preview.preview_id
        assert replayed_preview.replayed is True
        async with persistence_engine.connect() as connection:
            head_before_approval = await connection.scalar(
                select(BranchRow.head_revision_id).where(BranchRow.id == created.active_branch_id)
            )
        assert head_before_approval == created.root_revision_id

        decision_request = DecidePreviewRequest(
            preview_id=preview.preview_id,
            decision=PreviewDecision.APPROVE,
            actor_id="integration-test",
            idempotency_key=f"approve-{uuid4().hex}",
        )
        approved = await DecidePreview(uow)(decision_request)
        replayed_approval = await DecidePreview(uow)(decision_request)

        assert approved.revision_id is not None
        assert replayed_approval.revision_id == approved.revision_id
        assert replayed_approval.replayed is True

        async with persistence_engine.connect() as connection:
            branch_head = await connection.scalar(
                select(BranchRow.head_revision_id).where(BranchRow.id == created.active_branch_id)
            )
            preview_status = await connection.scalar(
                select(PreviewCandidateRow.status).where(
                    PreviewCandidateRow.id == preview.preview_id
                )
            )
            approval_count = await connection.scalar(
                select(func.count())
                .select_from(ApprovalRow)
                .where(ApprovalRow.preview_id == preview.preview_id)
            )
            materialize_command = await connection.scalar(
                select(RevisionCommandRow.command_type).where(
                    RevisionCommandRow.revision_id == approved.revision_id
                )
            )

        assert branch_head == approved.revision_id
        assert preview_status == "approved"
        assert approval_count == 1
        assert materialize_command == "materialize_candidate"
    finally:
        await _delete_exact_project(persistence_engine, created.project_id)


@pytest.mark.asyncio
async def test_usage_ledger_is_idempotent_by_provider_operation_id(
    persistence_engine: AsyncEngine,
) -> None:
    session_factory = create_session_factory(persistence_engine)
    recorder = PostgresTelemetryRecorder(session_factory)
    run_id = f"integration-run-{uuid4().hex}"
    operation_id = f"deepseek:integration-{uuid4().hex}"
    response = PlannerResponse(
        plan_payload={},
        usage=PlannerUsage(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            reasoning_tokens=3,
        ),
        provider="deepseek",
        model="deepseek-v4-flash",
        model_calls=1,
        operation_id=operation_id,
    )
    record = ModelCallRecord(
        operation_id=operation_id,
        run_id=run_id,
        thread_id=f"thread-{uuid4().hex}",
        node="CompositionPlanner",
        provider="deepseek",
        model="deepseek-v4-flash",
        prompt_version="composition-planner.v1",
        schema_version="composition-plan.v1",
        thinking_mode="enabled",
        response=response,
        status="succeeded",
    )

    await recorder.record_model_call(record)
    await recorder.record_model_call(record)

    try:
        async with persistence_engine.connect() as connection:
            span_count = await connection.scalar(
                select(func.count())
                .select_from(TraceSpanRow)
                .where(TraceSpanRow.operation_id == operation_id)
            )
            usage_count = await connection.scalar(
                select(func.count())
                .select_from(UsageLedgerRow)
                .where(UsageLedgerRow.operation_id == operation_id)
            )
            total_tokens = await connection.scalar(
                select(UsageLedgerRow.total_tokens).where(
                    UsageLedgerRow.operation_id == operation_id
                )
            )

        assert span_count == 1
        assert usage_count == 1
        assert total_tokens == 18
    finally:
        async with persistence_engine.begin() as connection:
            await connection.execute(
                delete(UsageLedgerRow).where(UsageLedgerRow.operation_id == operation_id)
            )
            await connection.execute(
                delete(TraceSpanRow).where(TraceSpanRow.operation_id == operation_id)
            )
            await connection.execute(delete(TraceRow).where(TraceRow.run_id == run_id))
