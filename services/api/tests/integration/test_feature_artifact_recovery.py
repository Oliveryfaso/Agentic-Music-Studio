from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from motif_forge.application.media_jobs import (
    ApplyWorkerEvent,
    EnqueueMediaJob,
    EnqueueMediaJobRequest,
    StartArtifactRehydration,
    StartArtifactRehydrationRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.storage import LocalArtifactCollector
from motif_forge.audio.features import write_feature_for_profile
from motif_forge.config import Settings
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
    FeatureArtifact,
    FeatureProfile,
    MediaJobType,
    MediaQualityProfile,
    RebuildInputArtifact,
    RebuildRecipe,
    WorkerEvent,
)
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import (
    PostgresMediaJobUnitOfWork,
    _feature_values,
)
from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    AuditEventRow,
    BranchRow,
    FeatureArtifactRow,
    IdempotencyRow,
    InboxReceiptRow,
    JobEventRow,
    MediaJobRow,
    MediaRunRow,
    OutboxEventRow,
    ProjectRow,
    RevisionRow,
    RunEventRow,
    StorageEventRow,
)
from motif_forge.worker.execution import execute_media_job
from sqlalchemy import delete, insert, select, text


@pytest.mark.asyncio
async def test_feature_eviction_and_rehydration_preserve_identity_and_checksum(
    test_postgres_dsn: str, tmp_path: Path
) -> None:
    engine = create_postgres_engine(test_postgres_dsn)
    session_factory = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(session_factory))(
        CreateProjectRequest(
            name="Feature recovery integration",
            actor_id="integration-test",
            idempotency_key=f"feature-project-{uuid4().hex}",
        )
    )
    media_uow = PostgresMediaJobUnitOfWork(session_factory)
    root = tmp_path / "artifacts"
    source_path = root / "protected/source.wav"
    source_path.parent.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=1:sample_rate=48000",
            "-ac",
            "2",
            str(source_path),
        ],
        check=True,
    )
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_job = await EnqueueMediaJob(media_uow)(
        EnqueueMediaJobRequest(
            project_id=project.project_id,
            thread_id=f"feature-source-{uuid4().hex}",
            run_type="feature_fixture",
            job_type=MediaJobType.INGEST,
            input_payload={"fixture": "source"},
            output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
            idempotency_key=f"feature-source-{uuid4().hex}",
        )
    )
    source = AudioArtifact(
        artifact_id=uuid4(),
        project_id=project.project_id,
        source_job_id=source_job.job_id,
        content_hash=source_hash,
        byte_size=source_path.stat().st_size,
        storage_key="protected/source.wav",
        media_role="normalized_import_audio",
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=1.0,
        bit_depth=16,
        encoder="ffmpeg",
        encoder_version="test",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        created_at=datetime.now(UTC),
    )
    await ApplyWorkerEvent(media_uow)(
        WorkerEvent(
            event_id=f"feature-source-complete-{uuid4().hex}",
            job_id=source_job.job_id,
            event_type="job.completed",
            artifact=source,
            occurred_at=datetime.now(UTC),
        )
    )
    output = write_feature_for_profile(
        source_path,
        artifact_root=root,
        project_id=project.project_id,
        source_content_hash=source_hash,
        profile=FeatureProfile.WAVEFORM_PEAKS_V1,
    )
    recipe = RebuildRecipe(
        recipe_id=uuid5(NAMESPACE_URL, f"motif-forge:feature-rebuild:{output.sha256}"),
        recipe_kind="analysis",
        input_artifacts=(
            RebuildInputArtifact(artifact_id=source.artifact_id, content_hash=source_hash),
        ),
        parameters={
            "feature_profile": output.feature_profile.value,
            "feature_schema_version": output.feature_schema_version,
            "timeout_seconds": 60.0,
        },
        engine="motif-forge-audio-features",
        engine_version="test",
        policy_version="audio-feature-policy.v1",
        output_feature_profile=FeatureProfile.WAVEFORM_PEAKS_V1,
        validation_rules=("json-schema.v1", "source-content-hash.v1"),
        idempotency_key=f"feature:{source_hash}:waveform-peaks.v1",
    )
    feature = FeatureArtifact(
        artifact_id=uuid4(),
        project_id=project.project_id,
        source_job_id=source_job.job_id,
        source_audio_artifact_id=source.artifact_id,
        source_audio_content_hash=source_hash,
        content_hash=output.sha256,
        byte_size=output.byte_size,
        storage_key=output.storage_key,
        feature_profile=FeatureProfile.WAVEFORM_PEAKS_V1,
        feature_schema_version=output.feature_schema_version,
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=datetime.now(UTC),
        last_accessed_at=datetime.now(UTC),
    )
    async with engine.begin() as connection:
        await connection.execute(insert(FeatureArtifactRow).values(**_feature_values(feature)))

    reclaimed = await LocalArtifactCollector(
        PostgresStorageUnitOfWork(session_factory), artifact_root=root
    )(operation_id=f"feature-evict-{feature.artifact_id}", artifact_ids=(feature.artifact_id,))
    assert reclaimed == output.byte_size
    assert not (root / output.storage_key).exists()

    queued = await StartArtifactRehydration(media_uow)(
        StartArtifactRehydrationRequest(
            project_id=project.project_id,
            artifact_id=feature.artifact_id,
            thread_id=f"feature-rehydrate-{feature.artifact_id}",
            idempotency_key=f"feature-rehydrate-{feature.artifact_id}",
        )
    )
    result = await execute_media_job(
        queued.job_id,
        settings=Settings(
            environment="test",
            postgres_dsn=test_postgres_dsn,
            artifact_root=root,
            temp_root=root / "tmp",
        ),
        worker_id="feature-integration-worker",
    )
    assert result.status == "succeeded"
    assert result.artifact_id == feature.artifact_id
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                select(
                    FeatureArtifactRow.availability,
                    FeatureArtifactRow.content_hash,
                ).where(FeatureArtifactRow.id == feature.artifact_id)
            )
        ).one()
    assert row.availability == ArtifactAvailability.AVAILABLE.value
    assert row.content_hash == output.sha256
    assert hashlib.sha256((root / output.storage_key).read_bytes()).hexdigest() == output.sha256

    async with engine.begin() as connection:
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        run_ids = select(MediaRunRow.id).where(MediaRunRow.project_id == project.project_id)
        job_ids = select(MediaJobRow.id).where(MediaJobRow.project_id == project.project_id)
        external_ids = select(JobEventRow.external_event_id).where(
            JobEventRow.job_id.in_(job_ids), JobEventRow.external_event_id.is_not(None)
        )
        await connection.execute(
            delete(StorageEventRow).where(StorageEventRow.project_id == project.project_id)
        )
        await connection.execute(
            delete(FeatureArtifactRow).where(FeatureArtifactRow.project_id == project.project_id)
        )
        await connection.execute(
            delete(AudioArtifactRow).where(AudioArtifactRow.project_id == project.project_id)
        )
        await connection.execute(
            delete(InboxReceiptRow).where(InboxReceiptRow.event_id.in_(external_ids))
        )
        await connection.execute(
            delete(OutboxEventRow).where(
                OutboxEventRow.aggregate_id.in_(run_ids) | OutboxEventRow.aggregate_id.in_(job_ids)
            )
        )
        await connection.execute(delete(JobEventRow).where(JobEventRow.job_id.in_(job_ids)))
        await connection.execute(delete(RunEventRow).where(RunEventRow.run_id.in_(run_ids)))
        await connection.execute(
            delete(MediaJobRow).where(MediaJobRow.project_id == project.project_id)
        )
        await connection.execute(
            delete(MediaRunRow).where(MediaRunRow.project_id == project.project_id)
        )
        await connection.execute(
            delete(AuditEventRow).where(AuditEventRow.project_id == project.project_id)
        )
        await connection.execute(
            delete(IdempotencyRow).where(IdempotencyRow.resource_id == project.project_id)
        )
        await connection.execute(
            delete(BranchRow).where(BranchRow.project_id == project.project_id)
        )
        await connection.execute(
            delete(RevisionRow).where(RevisionRow.project_id == project.project_id)
        )
        await connection.execute(delete(ProjectRow).where(ProjectRow.id == project.project_id))
    await engine.dispose()
