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
from motif_forge.application.ai_runs import CreateAIRun, CreateAIRunRequest
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.run_inspection import PostgresRunInspectionStore
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    MediaJobRow,
    MediaRunRow,
)
from sqlalchemy import insert, text


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


async def _delete_project(engine, project_id: UUID) -> None:  # type: ignore[no-untyped-def]
    async with engine.begin() as connection:
        for statement in (
            "DELETE FROM app.artifacts WHERE project_id=:project",
            "DELETE FROM app.job_events WHERE job_id IN "
            "(SELECT id FROM app.jobs WHERE project_id=:project)",
            "DELETE FROM app.run_events WHERE run_id IN "
            "(SELECT id FROM app.runs WHERE project_id=:project)",
            "DELETE FROM app.jobs WHERE project_id=:project",
            "DELETE FROM app.runs WHERE project_id=:project",
            "DELETE FROM app.outbox_events WHERE aggregate_id IN "
            "(SELECT id FROM app.ai_runs WHERE project_id=:project)",
            "DELETE FROM app.ai_run_events WHERE run_id IN "
            "(SELECT id FROM app.ai_runs WHERE project_id=:project)",
            "DELETE FROM app.ai_runs WHERE project_id=:project",
            "DELETE FROM app.audit_events WHERE project_id=:project",
            "DELETE FROM app.idempotency_records WHERE resource_id=:project OR resource_id IN "
            "(SELECT id FROM app.project_revisions WHERE project_id=:project)",
            "DELETE FROM app.project_branches WHERE project_id=:project",
            "DELETE FROM app.project_revisions WHERE project_id=:project",
            "DELETE FROM app.projects WHERE id=:project",
        ):
            await connection.execute(text(statement), {"project": project_id})


@pytest.mark.asyncio
async def test_postgres_run_inspection_is_repeatable_and_read_only(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(CreateProjectRequest(
        name=f"S7 Inspect {uuid4().hex}", actor_id="integration",
        idempotency_key=f"inspect-project-{uuid4().hex}",
    ))
    run = await CreateAIRun(PostgresAIRunUnitOfWork(sessions))(CreateAIRunRequest.model_validate({
        "project_id": project.project_id, "branch_id": project.active_branch_id,
        "base_revision_id": project.root_revision_id,
        "thread_id": f"inspect-{uuid4().hex}",
        "brief": {
            "title": "Inspection boundary", "purpose": "Read persisted Parent Graph facts",
            "style": "synth_ambient", "duration_seconds": 60, "moods": ("calm",),
        },
        "idempotency_key": f"inspect-run-{uuid4().hex}",
    }))
    try:
        async with engine.connect() as connection:
            before = tuple((await connection.execute(text(
                "SELECT (SELECT count(*) FROM app.ai_runs WHERE project_id=:project), "
                "(SELECT count(*) FROM app.ai_run_events WHERE run_id=:run), "
                "(SELECT count(*) FROM app.outbox_events WHERE aggregate_id=:run)"
            ), {"project": project.project_id, "run": run.run_id})).one())

        store = PostgresRunInspectionStore(sessions)
        first = await store.read_run_inspection(run.run_id)
        second = await store.read_run_inspection(run.run_id)

        async with engine.connect() as connection:
            after = tuple((await connection.execute(text(
                "SELECT (SELECT count(*) FROM app.ai_runs WHERE project_id=:project), "
                "(SELECT count(*) FROM app.ai_run_events WHERE run_id=:run), "
                "(SELECT count(*) FROM app.outbox_events WHERE aggregate_id=:run)"
            ), {"project": project.project_id, "run": run.run_id})).one())
        assert first == second
        assert first is not None and first.run.run_id == run.run_id
        assert first.versions.graph_topology_version == "motif-forge-parent.v2"
        assert first.usage.submitted_model_requests == 0
        assert before == after
        assert "brief" not in first.model_dump_json()
    finally:
        await _delete_project(engine, project.project_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_run_inspection_includes_pre_revision_thread_media(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    thread_id = f"inspect-preview-{uuid4().hex}"
    project = await CreateProject(PostgresUnitOfWork(sessions))(CreateProjectRequest(
        name=f"S7 Inspect Preview {uuid4().hex}", actor_id="integration",
        idempotency_key=f"inspect-preview-project-{uuid4().hex}",
    ))
    run = await CreateAIRun(PostgresAIRunUnitOfWork(sessions))(CreateAIRunRequest.model_validate({
        "project_id": project.project_id, "branch_id": project.active_branch_id,
        "base_revision_id": project.root_revision_id, "thread_id": thread_id,
        "brief": {
            "title": "Pre-revision inspection", "purpose": "Inspect candidate preview work",
            "style": "synth_ambient", "duration_seconds": 60, "moods": ("calm",),
        },
        "idempotency_key": f"inspect-preview-run-{uuid4().hex}",
    }))
    now = datetime.now(UTC)
    media_run_id, job_id, artifact_id = uuid4(), uuid4(), uuid4()
    try:
        async with sessions.begin() as session:
            await session.execute(insert(MediaRunRow).values(
                id=media_run_id, project_id=project.project_id, thread_id=thread_id,
                run_type="candidate_preview.v1", status="succeeded",
                waiting_for_job_id=job_id, schema_version="media-run.v1",
                created_at=now, updated_at=now,
            ))
            await session.execute(insert(MediaJobRow).values(
                id=job_id, run_id=media_run_id, project_id=project.project_id,
                job_type="render_preview", status="succeeded",
                idempotency_key=f"inspect-preview-job-{uuid4().hex}",
                request_hash="a" * 64, input_payload={"candidate": "A"},
                output_quality_profile="working-pcm.v1", output_feature_profile=None,
                result_artifact_id=artifact_id, error_code=None, attempts=1, max_attempts=3,
                deadline_at=now + timedelta(minutes=5), heartbeat_at=now,
                lease_owner=None, lease_expires_at=None, progress_percent=100,
                schema_version="media-job.v1", created_at=now, updated_at=now,
            ))
            await session.execute(insert(AudioArtifactRow).values(
                id=artifact_id, project_id=project.project_id,
                revision_id=None, candidate_snapshot_id=None, arrangement_hash=None,
                render_scope=None, render_track_ids=[], source_job_id=job_id,
                source_upload_id=None, content_hash="b" * 64, byte_size=4096,
                storage_key="protected/inspection/preview.wav", media_role="candidate_preview",
                quality_profile="working-pcm.v1", container="wav", codec="pcm_s16le",
                sample_rate_hz=48_000, channels=2, duration_milliseconds=30_000,
                bitrate_kbps=None, bit_depth=16, encoder="test", encoder_version="1",
                lifecycle_class="protected", availability="available",
                validation_status="validated", recipe_hash=None, rebuild_recipe=None,
                protection_reasons=[], analysis=None, last_accessed_at=None,
                expires_at=None, evicted_at=None, rehydration_job_id=None,
                schema_version="audio-artifact.v2", created_at=now,
            ))

        inspection = await PostgresRunInspectionStore(sessions).read_run_inspection(run.run_id)

        assert inspection is not None and inspection.run.revision_id is None
        assert tuple(item.job_id for item in inspection.jobs) == (job_id,)
        assert tuple(item.artifact_id for item in inspection.artifacts) == (artifact_id,)
    finally:
        await _delete_project(engine, project.project_id)
        await engine.dispose()
