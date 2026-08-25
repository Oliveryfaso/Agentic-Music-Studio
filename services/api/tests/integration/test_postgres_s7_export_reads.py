from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.generation import EXPORT_STEPS
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.export_reads import PostgresExportProjectionStore
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    MediaJobRow,
    MediaRunRow,
    RevisionRow,
)
from sqlalchemy import insert, select, text


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


async def _delete_project(engine, project_id: UUID) -> None:  # type: ignore[no-untyped-def]
    async with engine.begin() as connection:
        for statement in (
            "DELETE FROM app.artifacts WHERE project_id=:project",
            "DELETE FROM app.jobs WHERE project_id=:project",
            "DELETE FROM app.runs WHERE project_id=:project",
            "DELETE FROM app.audit_events WHERE project_id=:project",
            "DELETE FROM app.idempotency_records WHERE resource_id=:project OR resource_id IN "
            "(SELECT id FROM app.project_revisions WHERE project_id=:project)",
            "DELETE FROM app.project_branches WHERE project_id=:project",
            "DELETE FROM app.project_revisions WHERE project_id=:project",
            "DELETE FROM app.projects WHERE id=:project",
        ):
            await connection.execute(text(statement), {"project": project_id})


@pytest.mark.asyncio
async def test_postgres_export_projection_reads_safe_partial_lineage(
    test_postgres_dsn: str, tmp_path: Path,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(CreateProjectRequest(
        name=f"S7 Export {uuid4().hex}", actor_id="integration",
        idempotency_key=f"s7-export-{uuid4().hex}",
    ))
    now = datetime.now(UTC)
    media_run_id, job_id, artifact_id = uuid4(), uuid4(), uuid4()
    try:
        async with sessions.begin() as session:
            revision = (
                await session.execute(
                    select(RevisionRow).where(RevisionRow.id == project.root_revision_id)
                )
            ).scalar_one()
            await session.execute(insert(MediaRunRow).values(
                id=media_run_id, project_id=project.project_id,
                thread_id=f"s7-export-{uuid4().hex}",
                run_type="complete_song_export.v1", status="succeeded",
                waiting_for_job_id=job_id, schema_version="media-run.v1",
                created_at=now, updated_at=now,
            ))
            await session.execute(insert(MediaJobRow).values(
                id=job_id, run_id=media_run_id, project_id=project.project_id,
                job_type="render_canonical", status="succeeded",
                idempotency_key=f"s7-job-{uuid4().hex}", request_hash="a" * 64,
                input_payload={"revision_id": str(project.root_revision_id)},
                output_quality_profile="canonical-master.v1", output_feature_profile=None,
                result_artifact_id=artifact_id, error_code=None, attempts=1, max_attempts=3,
                deadline_at=now + timedelta(minutes=5), heartbeat_at=now,
                lease_owner=None, lease_expires_at=None, progress_percent=100,
                schema_version="media-job.v1", created_at=now, updated_at=now,
            ))
            await session.execute(insert(AudioArtifactRow).values(
                id=artifact_id, project_id=project.project_id,
                revision_id=project.root_revision_id, candidate_snapshot_id=None,
                arrangement_hash=revision.content_hash, render_scope="master",
                render_track_ids=[], source_job_id=job_id, source_upload_id=None,
                content_hash="b" * 64, byte_size=4096,
                storage_key="protected/s7/master.wav", media_role="master",
                quality_profile="canonical-master.v1", container="wav", codec="pcm_s24le",
                sample_rate_hz=48_000, channels=2, duration_milliseconds=60_000,
                bitrate_kbps=None, bit_depth=24, encoder="chromium",
                encoder_version="s7-test", lifecycle_class="protected",
                availability="available", validation_status="validated",
                recipe_hash=None, rebuild_recipe=None, protection_reasons=["final_export"],
                analysis=None, last_accessed_at=None, expires_at=None, evicted_at=None,
                rehydration_job_id=None, schema_version="audio-artifact.v2", created_at=now,
            ))

        store = PostgresExportProjectionStore(sessions, artifact_root=tmp_path)
        first = await store.read_revision_export(
            project_id=project.project_id, revision_id=project.root_revision_id
        )
        second = await store.read_revision_export(
            project_id=project.project_id, revision_id=project.root_revision_id
        )

        assert first == second
        assert first is not None and first.status == "partial"
        assert tuple(step.step for step in first.steps) == EXPORT_STEPS
        assert first.steps[0].job_id == job_id
        assert first.files[0].artifact_id == artifact_id
        assert "storage_key" not in first.model_dump_json()
    finally:
        await _delete_project(engine, project.project_id)
        await engine.dispose()
