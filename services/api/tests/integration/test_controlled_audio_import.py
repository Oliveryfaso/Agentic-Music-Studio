from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config
from motif_forge.application.media_jobs import EnqueueMediaJob, EnqueueMediaJobRequest
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.uploads import (
    CompleteUpload,
    CreateUploadSession,
    CreateUploadSessionRequest,
    PutUploadPart,
)
from motif_forge.audio.uploads import LocalUploadWorkspace
from motif_forge.config import Settings
from motif_forge.domain.media_jobs import (
    ArtifactValidationStatus,
    IngestJobPayload,
    MediaJobType,
    MediaQualityProfile,
)
from motif_forge.domain.uploads import DeclaredAudioFormat, RightsDeclaration
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
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
    UploadPartRow,
    UploadSessionRow,
)
from motif_forge.infrastructure.persistence.uploads import PostgresUploadUnitOfWork
from motif_forge.worker.execution import execute_media_job
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")


def _upgrade_database(dsn: str) -> None:
    project_root = Path(__file__).resolve().parents[4]
    config = Config(project_root / "alembic.ini")
    old = os.environ.get("MOTIF_FORGE_POSTGRES_DSN")
    os.environ["MOTIF_FORGE_POSTGRES_DSN"] = dsn
    try:
        alembic_command.upgrade(config, "head")
    finally:
        if old is None:
            os.environ.pop("MOTIF_FORGE_POSTGRES_DSN", None)
        else:
            os.environ["MOTIF_FORGE_POSTGRES_DSN"] = old


@pytest_asyncio.fixture
async def import_engine(test_postgres_dsn: str) -> AsyncIterator[AsyncEngine]:
    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


def _make_wav(path: Path) -> bytes:
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
            "sine=frequency=330:duration=0.2:sample_rate=44100",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


async def _body(value: bytes) -> AsyncIterator[bytes]:
    yield value


async def _delete_project(engine: AsyncEngine, project_id: object) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        run_ids = select(MediaRunRow.id).where(MediaRunRow.project_id == project_id)
        job_ids = select(MediaJobRow.id).where(MediaJobRow.project_id == project_id)
        external_ids = select(JobEventRow.external_event_id).where(
            JobEventRow.job_id.in_(job_ids), JobEventRow.external_event_id.is_not(None)
        )
        upload_ids = select(UploadSessionRow.id).where(UploadSessionRow.project_id == project_id)
        await connection.execute(
            delete(FeatureArtifactRow).where(FeatureArtifactRow.project_id == project_id)
        )
        await connection.execute(
            delete(AudioArtifactRow).where(AudioArtifactRow.project_id == project_id)
        )
        await connection.execute(
            delete(UploadPartRow).where(UploadPartRow.upload_id.in_(upload_ids))
        )
        await connection.execute(
            delete(UploadSessionRow).where(UploadSessionRow.project_id == project_id)
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
        await connection.execute(delete(MediaJobRow).where(MediaJobRow.project_id == project_id))
        await connection.execute(delete(MediaRunRow).where(MediaRunRow.project_id == project_id))
        await connection.execute(
            delete(AuditEventRow).where(AuditEventRow.project_id == project_id)
        )
        await connection.execute(
            delete(IdempotencyRow).where(IdempotencyRow.resource_id == project_id)
        )
        await connection.execute(delete(BranchRow).where(BranchRow.project_id == project_id))
        await connection.execute(delete(RevisionRow).where(RevisionRow.project_id == project_id))
        await connection.execute(delete(ProjectRow).where(ProjectRow.id == project_id))


@pytest.mark.asyncio
async def test_real_postgres_upload_registers_one_quarantined_source_artifact(
    import_engine: AsyncEngine, tmp_path: Path
) -> None:
    session_factory = create_session_factory(import_engine)
    token = uuid4().hex
    project = await CreateProject(PostgresUnitOfWork(session_factory))(
        CreateProjectRequest(
            name="Import Integration",
            actor_id="integration-test",
            idempotency_key=f"project-{token}",
        )
    )
    source_path = tmp_path / "source.wav"
    value = _make_wav(source_path)
    checksum = hashlib.sha256(value).hexdigest()
    root = tmp_path / "artifacts"
    workspace = LocalUploadWorkspace(root)
    uow = PostgresUploadUnitOfWork(session_factory)

    upload = await CreateUploadSession(
        uow,
        max_upload_bytes=8 * 1024 * 1024,
        part_size_bytes=1024 * 1024,
        ttl_hours=1,
        artifact_root=root,
        min_free_bytes=1024,
    )(
        CreateUploadSessionRequest(
            project_id=project.project_id,
            original_filename="source.wav",
            declared_format=DeclaredAudioFormat.WAV,
            rights_declaration=RightsDeclaration.USER_OWNED,
            expected_sha256=checksum,
            byte_size=len(value),
            idempotency_key=f"upload-{token}",
        )
    )
    try:
        await PutUploadPart(uow, workspace)(
            upload_id=upload.upload_id, part_number=1, body=_body(value)
        )
        completed = await CompleteUpload(uow, workspace)(upload.upload_id)
        replay = await CompleteUpload(uow, workspace)(upload.upload_id)

        assert replay.source_artifact_id == completed.source_artifact_id
        assert replay.replayed is True
        async with import_engine.connect() as connection:
            row = (
                await connection.execute(
                    select(
                        AudioArtifactRow.source_job_id,
                        AudioArtifactRow.source_upload_id,
                        AudioArtifactRow.validation_status,
                        AudioArtifactRow.sample_rate_hz,
                    ).where(AudioArtifactRow.id == completed.source_artifact_id)
                )
            ).one()
            assert row.source_job_id is None
            assert row.source_upload_id == upload.upload_id
            assert row.validation_status == ArtifactValidationStatus.QUARANTINED.value
            assert row.sample_rate_hz is None
    finally:
        await _delete_project(import_engine, project.project_id)


@pytest.mark.asyncio
async def test_ingest_worker_validates_source_and_persists_normalized_artifact(
    import_engine: AsyncEngine, test_postgres_dsn: str, tmp_path: Path
) -> None:
    session_factory = create_session_factory(import_engine)
    token = uuid4().hex
    project = await CreateProject(PostgresUnitOfWork(session_factory))(
        CreateProjectRequest(
            name="Ingest Worker Integration",
            actor_id="integration-test",
            idempotency_key=f"project-{token}",
        )
    )
    source_path = tmp_path / "source.wav"
    value = _make_wav(source_path)
    checksum = hashlib.sha256(value).hexdigest()
    root = tmp_path / "artifacts"
    workspace = LocalUploadWorkspace(root)
    upload_uow = PostgresUploadUnitOfWork(session_factory)
    upload = await CreateUploadSession(
        upload_uow,
        max_upload_bytes=8 * 1024 * 1024,
        part_size_bytes=1024 * 1024,
        ttl_hours=1,
        artifact_root=root,
        min_free_bytes=1024,
    )(
        CreateUploadSessionRequest(
            project_id=project.project_id,
            original_filename="source.wav",
            declared_format=DeclaredAudioFormat.WAV,
            rights_declaration=RightsDeclaration.USER_OWNED,
            expected_sha256=checksum,
            byte_size=len(value),
            idempotency_key=f"upload-{token}",
        )
    )
    try:
        await PutUploadPart(upload_uow, workspace)(
            upload_id=upload.upload_id, part_number=1, body=_body(value)
        )
        completed = await CompleteUpload(upload_uow, workspace)(upload.upload_id)
        payload = IngestJobPayload(source_artifact_id=completed.source_artifact_id)
        queued = await EnqueueMediaJob(PostgresMediaJobUnitOfWork(session_factory))(
            EnqueueMediaJobRequest(
                project_id=project.project_id,
                thread_id=f"import-{token}",
                run_type="parent.import_audio.v1",
                job_type=MediaJobType.INGEST,
                input_payload=payload.model_dump(mode="json"),
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=f"ingest-{token}",
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
            worker_id="integration-worker",
        )

        assert result.status == "succeeded"
        assert result.artifact_id is not None
        async with import_engine.connect() as connection:
            source_row = (
                await connection.execute(
                    select(
                        AudioArtifactRow.validation_status,
                        AudioArtifactRow.sample_rate_hz,
                        AudioArtifactRow.channels,
                    ).where(AudioArtifactRow.id == completed.source_artifact_id)
                )
            ).one()
            normalized_row = (
                await connection.execute(
                    select(
                        AudioArtifactRow.storage_key,
                        AudioArtifactRow.sample_rate_hz,
                        AudioArtifactRow.channels,
                        AudioArtifactRow.bit_depth,
                        AudioArtifactRow.analysis,
                    ).where(AudioArtifactRow.id == result.artifact_id)
                )
            ).one()
            feature_rows = (
                await connection.execute(
                    select(
                        FeatureArtifactRow.id,
                        FeatureArtifactRow.feature_profile,
                        FeatureArtifactRow.storage_key,
                        FeatureArtifactRow.lifecycle_class,
                        FeatureArtifactRow.rebuild_recipe,
                    ).where(
                        FeatureArtifactRow.source_audio_artifact_id == result.artifact_id
                    )
                )
            ).all()
        assert source_row.validation_status == ArtifactValidationStatus.VALIDATED.value
        assert source_row.sample_rate_hz == 44_100
        assert source_row.channels == 1
        assert normalized_row.sample_rate_hz == 48_000
        assert normalized_row.channels == 2
        assert normalized_row.bit_depth == 16
        assert normalized_row.analysis["analysis_version"] == "import-analysis.v1"
        assert normalized_row.analysis["bpm_confidence"] == 0.0
        assert (root / normalized_row.storage_key).is_file()
        assert {row.feature_profile for row in feature_rows} == {
            "waveform-peaks.v1",
            "imported-audio-analysis.v1",
        }
        assert all(row.lifecycle_class == "rebuildable" for row in feature_rows)
        assert all(row.rebuild_recipe["recipe_kind"] == "analysis" for row in feature_rows)
        assert all((root / row.storage_key).is_file() for row in feature_rows)
    finally:
        await _delete_project(import_engine, project.project_id)
