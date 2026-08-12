from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from motif_forge.application.errors import MediaJobStateConflictError
from motif_forge.application.media_jobs import (
    ApplyWorkerEvent,
    CancelMediaJob,
    CancelMediaJobRequest,
    EnqueueMediaJob,
    EnqueueMediaJobRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.audio.chromium_render import CanonicalRenderResult
from motif_forge.config import Settings
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    CanonicalRenderJobPayload,
    JobStatus,
    MediaJobType,
    MediaQualityProfile,
    RenderScope,
    WorkerEvent,
)
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.tables import OutboxEventRow
from motif_forge.worker.execution import (
    _apply_worker_event_fail_closed,
    execute_media_job,
)
from sqlalchemy import select


def _upgrade_database(dsn: str) -> None:
    project_root = Path(__file__).resolve().parents[4]
    config = Config(project_root / "alembic.ini")
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        alembic_command.upgrade(config, "head")


@pytest.mark.asyncio
async def test_render_job_and_outbox_are_atomic_and_idempotent(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name="S1 Render",
            actor_id="integration",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    request = EnqueueMediaJobRequest(
        project_id=project.project_id,
        thread_id=f"s1-render-{uuid4().hex}",
        run_type="parent.s1_render.v1",
        job_type=MediaJobType.RENDER_CANONICAL,
        input_payload={"schema_version": "canonical-render-job.v1"},
        output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        idempotency_key=f"render-{uuid4().hex}",
        deadline_seconds=300,
    )
    enqueue = EnqueueMediaJob(PostgresMediaJobUnitOfWork(sessions))

    first = await enqueue(request)
    replay = await enqueue(request)

    assert replay.job_id == first.job_id
    assert replay.replayed
    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    select(OutboxEventRow).where(OutboxEventRow.aggregate_id == first.job_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].topic == "media.job.dispatch.requested"

    cancelled = await CancelMediaJob(PostgresMediaJobUnitOfWork(sessions))(
        CancelMediaJobRequest(job_id=first.job_id, actor_id="local-user:integration")
    )
    assert cancelled.status is JobStatus.CANCELLED
    execution = await execute_media_job(
        first.job_id,
        settings=Settings(
            environment="test",
            postgres_dsn=test_postgres_dsn,
            artifact_root=tmp_path,
            temp_root=tmp_path / "tmp",
            storage_min_free_bytes=64 * 1024**2,
        ),
        worker_id="cancel-test",
    )
    assert execution.status == JobStatus.CANCELLED.value
    assert execution.error_code == "MEDIA_JOB_CANCELLED"
    await engine.dispose()


@pytest.mark.asyncio
async def test_render_job_stops_at_storage_pressure_gate_before_render(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name="S1 storage pressure",
            actor_id="integration",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    projection = compile_audio_graph(build_s1_composition(project.project_id, seed=1).arrangement)
    payload = CanonicalRenderJobPayload(
        project_id=project.project_id,
        revision_id=project.root_revision_id,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version="motif-forge-audio-engine.v1",
        seed=1,
        timeout_seconds=30,
        maximum_output_bytes=64 * 1024**2,
    )
    queued = await EnqueueMediaJob(PostgresMediaJobUnitOfWork(sessions))(
        EnqueueMediaJobRequest(
            project_id=project.project_id,
            thread_id=f"s1-pressure-{uuid4().hex}",
            run_type="parent.s1_render.v1",
            job_type=MediaJobType.RENDER_CANONICAL,
            input_payload=payload.model_dump(mode="json"),
            output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            idempotency_key=f"render-{uuid4().hex}",
            deadline_seconds=300,
        )
    )
    result = await execute_media_job(
        queued.job_id,
        settings=Settings(
            environment="test",
            postgres_dsn=test_postgres_dsn,
            artifact_root=tmp_path,
            temp_root=tmp_path / "tmp",
            artifact_global_quota_bytes=10 * 1024**3,
            artifact_project_quota_bytes=1024**2,
            temp_quota_bytes=1024**2,
            upload_max_bytes=1024**2,
            upload_part_size_bytes=64 * 1024,
            storage_min_free_bytes=64 * 1024**2,
        ),
        worker_id="pressure-test",
    )
    assert result.status == JobStatus.FAILED_RETRYABLE.value
    assert result.error_code == "STORAGE_QUOTA_EXCEEDED"
    await engine.dispose()


@pytest.mark.asyncio
async def test_running_render_job_observes_persisted_cancellation(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name="S1 running cancellation",
            actor_id="integration",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    projection = compile_audio_graph(build_s1_composition(project.project_id, seed=2).arrangement)
    payload = CanonicalRenderJobPayload(
        project_id=project.project_id,
        revision_id=project.root_revision_id,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version="motif-forge-audio-engine.v1",
        seed=2,
        timeout_seconds=30,
        maximum_output_bytes=64 * 1024**2,
    )
    queued = await EnqueueMediaJob(PostgresMediaJobUnitOfWork(sessions))(
        EnqueueMediaJobRequest(
            project_id=project.project_id,
            thread_id=f"s1-cancel-{uuid4().hex}",
            run_type="parent.s1_render.v1",
            job_type=MediaJobType.RENDER_CANONICAL,
            input_payload=payload.model_dump(mode="json"),
            output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            idempotency_key=f"render-{uuid4().hex}",
            deadline_seconds=300,
        )
    )
    started = asyncio.Event()

    async def blocking_render(*args, **kwargs):
        del args, kwargs
        started.set()
        await asyncio.Event().wait()

    settings = Settings(
        environment="test",
        postgres_dsn=test_postgres_dsn,
        artifact_root=tmp_path,
        temp_root=tmp_path / "tmp",
        storage_min_free_bytes=64 * 1024**2,
    )
    with patch("motif_forge.worker.execution._execute_canonical_render", blocking_render):
        execution = asyncio.create_task(
            execute_media_job(queued.job_id, settings=settings, worker_id="running-cancel-test")
        )
        await asyncio.wait_for(started.wait(), timeout=3)
        await CancelMediaJob(PostgresMediaJobUnitOfWork(sessions))(
            CancelMediaJobRequest(job_id=queued.job_id, actor_id="local-user:integration")
        )
        result = await asyncio.wait_for(execution, timeout=3)

    assert result.status == JobStatus.CANCELLED.value
    assert result.error_code == "MEDIA_JOB_CANCELLED"
    await engine.dispose()


@pytest.mark.asyncio
async def test_render_promotion_racing_with_cancel_removes_created_output(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name="S1 promotion cancellation race",
            actor_id="integration",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    projection = compile_audio_graph(build_s1_composition(project.project_id, seed=3).arrangement)
    payload = CanonicalRenderJobPayload(
        project_id=project.project_id,
        revision_id=project.root_revision_id,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version="motif-forge-audio-engine.v1",
        seed=3,
        timeout_seconds=30,
        maximum_output_bytes=64 * 1024**2,
    )
    queued = await EnqueueMediaJob(PostgresMediaJobUnitOfWork(sessions))(
        EnqueueMediaJobRequest(
            project_id=project.project_id,
            thread_id=f"s1-promote-cancel-{uuid4().hex}",
            run_type="parent.s1_render.v1",
            job_type=MediaJobType.RENDER_CANONICAL,
            input_payload=payload.model_dump(mode="json"),
            output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            idempotency_key=f"render-{uuid4().hex}",
            deadline_seconds=300,
        )
    )
    promoted = asyncio.Event()
    release_result = asyncio.Event()
    storage_key = (
        f"protected/exports/{project.project_id}/{project.root_revision_id}/audio/"
        "promoted-master.wav"
    )
    output = tmp_path / storage_key

    async def promote_then_wait(*args, **kwargs):
        del args, kwargs
        output.parent.mkdir(parents=True)
        output.write_bytes(b"promoted-audio")
        promoted.set()
        await release_result.wait()
        return CanonicalRenderResult(
            storage_key=storage_key,
            sha256="a" * 64,
            byte_size=14,
            duration_seconds=72.0,
            sample_rate_hz=48_000,
            channels=2,
            bit_depth=24,
            peak=0.5,
            created_new=True,
        )

    settings = Settings(
        environment="test",
        postgres_dsn=test_postgres_dsn,
        artifact_root=tmp_path,
        temp_root=tmp_path / "explicit-temp",
        storage_min_free_bytes=64 * 1024**2,
    )
    with patch("motif_forge.worker.execution._execute_canonical_render", promote_then_wait):
        execution = asyncio.create_task(
            execute_media_job(queued.job_id, settings=settings, worker_id="promote-cancel-test")
        )
        await asyncio.wait_for(promoted.wait(), timeout=3)
        await CancelMediaJob(PostgresMediaJobUnitOfWork(sessions))(
            CancelMediaJobRequest(job_id=queued.job_id, actor_id="local-user:integration")
        )
        release_result.set()
        result = await asyncio.wait_for(execution, timeout=3)

    assert result.status == JobStatus.CANCELLED.value
    assert not output.exists()
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_before_completion_event_removes_created_output(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name="S1 completion cancellation race",
            actor_id="integration",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    projection = compile_audio_graph(build_s1_composition(project.project_id, seed=4).arrangement)
    payload = CanonicalRenderJobPayload(
        project_id=project.project_id,
        revision_id=project.root_revision_id,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version="motif-forge-audio-engine.v1",
        seed=4,
        timeout_seconds=30,
        maximum_output_bytes=64 * 1024**2,
    )
    queued = await EnqueueMediaJob(PostgresMediaJobUnitOfWork(sessions))(
        EnqueueMediaJobRequest(
            project_id=project.project_id,
            thread_id=f"s1-event-cancel-{uuid4().hex}",
            run_type="parent.s1_render.v1",
            job_type=MediaJobType.RENDER_CANONICAL,
            input_payload=payload.model_dump(mode="json"),
            output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            idempotency_key=f"render-{uuid4().hex}",
            deadline_seconds=300,
        )
    )
    storage_key = (
        f"protected/exports/{project.project_id}/{project.root_revision_id}/audio/"
        "event-race-master.wav"
    )
    output = tmp_path / storage_key

    async def promote(*args, **kwargs):
        del args, kwargs
        output.parent.mkdir(parents=True)
        output.write_bytes(b"promoted-audio")
        return CanonicalRenderResult(
            storage_key=storage_key,
            sha256="b" * 64,
            byte_size=14,
            duration_seconds=72.0,
            sample_rate_hz=48_000,
            channels=2,
            bit_depth=24,
            peak=0.5,
            created_new=True,
        )

    def cancel_before_apply(uow):
        real_apply_worker_event = ApplyWorkerEvent

        async def apply(event):
            await CancelMediaJob(PostgresMediaJobUnitOfWork(sessions))(
                CancelMediaJobRequest(job_id=queued.job_id, actor_id="local-user:integration")
            )
            return await real_apply_worker_event(uow)(event)

        return apply

    settings = Settings(
        environment="test",
        postgres_dsn=test_postgres_dsn,
        artifact_root=tmp_path,
        temp_root=tmp_path / "explicit-temp",
        storage_min_free_bytes=64 * 1024**2,
    )
    with (
        patch("motif_forge.worker.execution._execute_canonical_render", promote),
        patch("motif_forge.worker.execution.ApplyWorkerEvent", cancel_before_apply),
    ):
        result = await execute_media_job(
            queued.job_id,
            settings=settings,
            worker_id="event-cancel-test",
        )

    assert result.status == JobStatus.CANCELLED.value
    assert not output.exists()
    await engine.dispose()


@pytest.mark.asyncio
async def test_succeeded_job_rejects_divergent_duplicate_completion_and_cleans_output(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name="S1 divergent completion",
            actor_id="integration",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    queued = await EnqueueMediaJob(PostgresMediaJobUnitOfWork(sessions))(
        EnqueueMediaJobRequest(
            project_id=project.project_id,
            thread_id=f"s1-divergent-{uuid4().hex}",
            run_type="parent.s1_render.v1",
            job_type=MediaJobType.RENDER_CANONICAL,
            input_payload={"schema_version": "canonical-render-job.v1"},
            output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            idempotency_key=f"render-{uuid4().hex}",
            deadline_seconds=300,
        )
    )
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    artifact_a = AudioArtifact(
        artifact_id=uuid4(),
        project_id=project.project_id,
        revision_id=project.root_revision_id,
        arrangement_hash="a" * 64,
        render_scope=RenderScope.MASTER,
        source_job_id=queued.job_id,
        content_hash="1" * 64,
        byte_size=10,
        storage_key="protected/exports/a.wav",
        media_role="canonical_master",
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        container="wav",
        codec="pcm",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=72.0,
        bit_depth=24,
        encoder="test",
        encoder_version="test.v1",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        created_at=now,
    )
    await ApplyWorkerEvent(PostgresMediaJobUnitOfWork(sessions))(
        WorkerEvent(
            event_id=f"job:{queued.job_id}:completed:a",
            job_id=queued.job_id,
            event_type="job.completed",
            artifact=artifact_a,
            occurred_at=now,
        )
    )
    divergent_key = "protected/exports/divergent-b.wav"
    divergent_path = tmp_path / divergent_key
    divergent_path.parent.mkdir(parents=True)
    divergent_path.write_bytes(b"divergent")
    artifact_b = artifact_a.model_copy(
        update={
            "artifact_id": uuid4(),
            "content_hash": "2" * 64,
            "byte_size": len(b"divergent"),
            "storage_key": divergent_key,
        }
    )
    event_b = WorkerEvent(
        event_id=f"job:{queued.job_id}:completed:b",
        job_id=queued.job_id,
        event_type="job.completed",
        artifact=artifact_b,
        occurred_at=now,
    )
    media_result_b = CanonicalRenderResult(
        storage_key=divergent_key,
        sha256="2" * 64,
        byte_size=len(b"divergent"),
        duration_seconds=72.0,
        sample_rate_hz=48_000,
        channels=2,
        bit_depth=24,
        peak=0.5,
        created_new=True,
    )

    with pytest.raises(MediaJobStateConflictError):
        await _apply_worker_event_fail_closed(
            event_b,
            uow=PostgresMediaJobUnitOfWork(sessions),
            media_result=media_result_b,
            artifact_root=tmp_path,
        )

    assert not divergent_path.exists()
    await engine.dispose()
