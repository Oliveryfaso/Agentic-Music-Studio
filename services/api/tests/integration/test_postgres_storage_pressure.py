from __future__ import annotations

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
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
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
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    AuditEventRow,
    BranchRow,
    FeatureArtifactRow,
    IdempotencyRow,
    JobEventRow,
    MediaJobRow,
    MediaRunRow,
    OutboxEventRow,
    ProjectRow,
    RevisionRow,
    RunEventRow,
    StorageEventRow,
)
from sqlalchemy import delete, insert, select


@pytest.mark.asyncio
async def test_real_postgres_eviction_is_exact_and_preserves_recipe(
    test_postgres_dsn: str, tmp_path: Path
) -> None:
    engine = create_postgres_engine(test_postgres_dsn)
    session_factory = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(session_factory))(
        CreateProjectRequest(
            name="Storage pressure integration",
            actor_id="integration-test",
            idempotency_key=f"storage-project-{uuid4().hex}",
        )
    )
    artifact_root = tmp_path / "artifacts"
    source_path = artifact_root / "protected/source.wav"
    derived_path = artifact_root / "derived/result.wav"
    source_path.parent.mkdir(parents=True)
    derived_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"source")
    derived_path.write_bytes(b"derived")
    source_id = uuid4()
    derived_id = uuid4()
    media_uow = PostgresMediaJobUnitOfWork(session_factory)
    source_job = (
        await EnqueueMediaJob(media_uow)(
            EnqueueMediaJobRequest(
                project_id=project.project_id,
                thread_id=f"storage-source-{uuid4().hex}",
                run_type="storage_fixture",
                job_type=MediaJobType.INGEST,
                input_payload={"fixture": "source"},
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=f"storage-source-{uuid4().hex}",
            )
        )
    ).job_id
    derived_job = (
        await EnqueueMediaJob(media_uow)(
            EnqueueMediaJobRequest(
                project_id=project.project_id,
                thread_id=f"storage-derived-{uuid4().hex}",
                run_type="storage_fixture",
                job_type=MediaJobType.TIME_STRETCH,
                input_payload={"fixture": "derived"},
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=f"storage-derived-{uuid4().hex}",
            )
        )
    ).job_id
    recipe = RebuildRecipe(
        recipe_id=uuid5(NAMESPACE_URL, f"storage-recipe:{derived_id}"),
        recipe_kind="time_stretch",
        input_artifacts=(RebuildInputArtifact(artifact_id=source_id, content_hash="a" * 64),),
        parameters={
            "source_bpm": 100.0,
            "target_bpm": 120.0,
            "preserve_pitch": True,
            "timeout_seconds": 60.0,
        },
        engine="ffmpeg-atempo",
        engine_version="7.1",
        policy_version="time-stretch-quality-policy.v1",
        output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        expected_container="wav",
        expected_codec="pcm",
        expected_sample_rate_hz=48_000,
        expected_channels=2,
        expected_bit_depth=16,
        validation_rules=("duration-tolerance.v1",),
        idempotency_key=f"rehydrate:{derived_id}",
    )
    now = datetime.now(UTC)
    source = AudioArtifact(
        artifact_id=source_id,
        project_id=project.project_id,
        source_job_id=source_job,
        content_hash="a" * 64,
        byte_size=6,
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
        encoder_version="7.1",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        protection_reasons=("import-source",),
        created_at=now,
        last_accessed_at=now,
    )
    derived = AudioArtifact(
        artifact_id=derived_id,
        project_id=project.project_id,
        source_job_id=derived_job,
        content_hash="b" * 64,
        byte_size=7,
        storage_key="derived/result.wav",
        media_role="time_stretched_audio",
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=1.0,
        bit_depth=16,
        encoder="ffmpeg-atempo",
        encoder_version="7.1",
        lifecycle_class=ArtifactLifecycle.REBUILDABLE,
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=now,
        last_accessed_at=now,
    )
    try:
        async with engine.begin() as connection:
            for artifact in (source, derived):
                await connection.execute(
                    insert(AudioArtifactRow).values(
                        id=artifact.artifact_id,
                        project_id=artifact.project_id,
                        source_job_id=artifact.source_job_id,
                        source_upload_id=None,
                        content_hash=artifact.content_hash,
                        byte_size=artifact.byte_size,
                        storage_key=artifact.storage_key,
                        media_role=artifact.media_role,
                        quality_profile=artifact.quality_profile.value,
                        container=artifact.container,
                        codec=artifact.codec,
                        sample_rate_hz=artifact.sample_rate_hz,
                        channels=artifact.channels,
                        duration_milliseconds=1000,
                        bitrate_kbps=None,
                        bit_depth=16,
                        encoder=artifact.encoder,
                        encoder_version=artifact.encoder_version,
                        lifecycle_class=artifact.lifecycle_class.value,
                        availability=artifact.availability.value,
                        validation_status=artifact.validation_status.value,
                        recipe_hash=artifact.recipe_hash,
                        rebuild_recipe=(
                            artifact.rebuild_recipe.model_dump(mode="json")
                            if artifact.rebuild_recipe
                            else None
                        ),
                        protection_reasons=list(artifact.protection_reasons),
                        analysis=None,
                        last_accessed_at=artifact.last_accessed_at,
                        expires_at=None,
                        evicted_at=None,
                        rehydration_job_id=None,
                        schema_version=artifact.schema_version,
                        created_at=now,
                    )
                )
        collector = LocalArtifactCollector(
            PostgresStorageUnitOfWork(session_factory), artifact_root=artifact_root
        )
        reclaimed = await collector(
            operation_id="postgres-storage-operation", artifact_ids=(source_id, derived_id)
        )

        assert reclaimed == 7
        assert source_path.read_bytes() == b"source"
        assert not derived_path.exists()
        rehydration = await StartArtifactRehydration(media_uow)(
            StartArtifactRehydrationRequest(
                project_id=project.project_id,
                artifact_id=derived_id,
                thread_id=f"rehydrate-{derived_id}",
                idempotency_key=f"rehydrate-public-{derived_id}",
            )
        )
        async with engine.connect() as connection:
            rehydrating = (
                await connection.execute(
                    select(
                        AudioArtifactRow.availability,
                        AudioArtifactRow.rehydration_job_id,
                    ).where(AudioArtifactRow.id == derived_id)
                )
            ).one()
        assert rehydrating.availability == ArtifactAvailability.REHYDRATING.value
        assert rehydrating.rehydration_job_id == rehydration.job_id

        derived_path.write_bytes(b"derived")
        completed_at = datetime.now(UTC)
        await ApplyWorkerEvent(media_uow)(
            WorkerEvent(
                event_id=f"rehydrate-complete-{rehydration.job_id}",
                job_id=rehydration.job_id,
                event_type="job.completed",
                artifact=derived.model_copy(
                    update={
                        "source_job_id": rehydration.job_id,
                        "availability": ArtifactAvailability.AVAILABLE,
                        "evicted_at": None,
                        "rehydration_job_id": None,
                        "created_at": completed_at,
                        "last_accessed_at": completed_at,
                    }
                ),
                occurred_at=completed_at,
            )
        )
        replay = await StartArtifactRehydration(media_uow)(
            StartArtifactRehydrationRequest(
                project_id=project.project_id,
                artifact_id=derived_id,
                thread_id=f"rehydrate-{derived_id}",
                idempotency_key=f"rehydrate-public-{derived_id}",
            )
        )
        assert replay.job_id == rehydration.job_id
        assert replay.replayed is True
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    select(
                        AudioArtifactRow.availability,
                        AudioArtifactRow.rebuild_recipe,
                    ).where(AudioArtifactRow.id == derived_id)
                )
            ).one()
            assert row.availability == ArtifactAvailability.AVAILABLE.value
            assert row.rebuild_recipe["recipe_id"] == str(recipe.recipe_id)
            assert (
                await connection.execute(
                    select(StorageEventRow.id).where(
                        StorageEventRow.operation_id == "postgres-storage-operation",
                        StorageEventRow.event_type == "artifact.evicted",
                    )
                )
            ).first()
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(FeatureArtifactRow).where(
                    FeatureArtifactRow.project_id == project.project_id
                )
            )
            await connection.execute(
                delete(StorageEventRow).where(StorageEventRow.project_id == project.project_id)
            )
            await connection.execute(
                delete(AudioArtifactRow).where(AudioArtifactRow.project_id == project.project_id)
            )
            run_ids = select(MediaRunRow.id).where(MediaRunRow.project_id == project.project_id)
            job_ids = select(MediaJobRow.id).where(MediaJobRow.project_id == project.project_id)
            await connection.execute(
                delete(OutboxEventRow).where(
                    OutboxEventRow.aggregate_id.in_(run_ids)
                    | OutboxEventRow.aggregate_id.in_(job_ids)
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
