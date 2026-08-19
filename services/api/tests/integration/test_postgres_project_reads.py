from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.ai_runs import CreateAIRun, CreateAIRunRequest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.media_jobs import (
    ApplyWorkerEvent,
    EnqueueMediaJob,
    EnqueueMediaJobRequest,
)
from motif_forge.application.project_reads import ReadRevisionStudio
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    MediaJobType,
    MediaQualityProfile,
    RenderScope,
    WorkerEvent,
)
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.project_reads import PostgresProjectReadStore
from motif_forge.infrastructure.persistence.tables import BranchRow, ProjectRow, RevisionRow
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


async def _delete_exact_project(engine: AsyncEngine, project_id: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        statements = (
            "DELETE FROM app.export_bundle_artifacts WHERE project_id=:project",
            "DELETE FROM app.artifacts WHERE project_id=:project",
            "DELETE FROM app.outbox_events WHERE aggregate_id IN "
            "(SELECT id FROM app.jobs WHERE project_id=:project) OR aggregate_id IN "
            "(SELECT id FROM app.runs WHERE project_id=:project) OR aggregate_id IN "
            "(SELECT id FROM app.ai_runs WHERE project_id=:project)",
            "DELETE FROM app.job_events WHERE job_id IN "
            "(SELECT id FROM app.jobs WHERE project_id=:project)",
            "DELETE FROM app.run_events WHERE run_id IN "
            "(SELECT id FROM app.runs WHERE project_id=:project)",
            "DELETE FROM app.jobs WHERE project_id=:project",
            "DELETE FROM app.runs WHERE project_id=:project",
            "DELETE FROM app.composition_materialization_receipts WHERE run_id IN "
            "(SELECT id FROM app.ai_runs WHERE project_id=:project)",
            "DELETE FROM app.ai_runs WHERE project_id=:project",
            "DELETE FROM app.audit_events WHERE project_id=:project",
            "DELETE FROM app.approvals WHERE project_id=:project",
            "DELETE FROM app.idempotency_records WHERE resource_id=:project OR resource_id IN "
            "(SELECT id FROM app.preview_candidates WHERE project_id=:project) OR "
            "resource_id IN (SELECT id FROM app.project_revisions WHERE project_id=:project)",
            "DELETE FROM app.preview_candidates WHERE project_id=:project",
            "DELETE FROM app.candidate_snapshots WHERE project_id=:project",
            "DELETE FROM app.revision_commands WHERE revision_id IN "
            "(SELECT id FROM app.project_revisions WHERE project_id=:project)",
            "DELETE FROM app.command_batches WHERE project_id=:project",
            "DELETE FROM app.project_branches WHERE project_id=:project",
            "DELETE FROM app.project_revisions WHERE project_id=:project",
            "DELETE FROM app.projects WHERE id=:project",
        )
        for statement in statements:
            await connection.execute(text(statement), {"project": project_id})


@pytest.mark.asyncio
async def test_real_postgres_projects_and_studio_reads_are_bounded_and_lineage_safe(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project_uow = PostgresUnitOfWork(sessions)
    first = await CreateProject(project_uow)(CreateProjectRequest(
        name=f"S3 Read {uuid4().hex}", actor_id="integration",
        idempotency_key=f"s3-read-{uuid4().hex}",
    ))
    other = await CreateProject(project_uow)(CreateProjectRequest(
        name=f"S3 Other {uuid4().hex}", actor_id="integration",
        idempotency_key=f"s3-other-{uuid4().hex}",
    ))
    revision_id = uuid4()
    now = datetime.now(UTC)
    try:
        async with sessions.begin() as session:
            root = (
                await session.execute(
                    select(RevisionRow).where(RevisionRow.id == first.root_revision_id)
                )
            ).scalar_one()
            await session.execute(insert(RevisionRow).values(
                id=revision_id,
                project_id=first.project_id,
                parent_id=first.root_revision_id,
                created_on_branch_id=first.active_branch_id,
                arrangement_ir=root.arrangement_ir,
                content_hash=root.content_hash,
                command_batch_id=None,
                change_impact_predicted=0,
                change_impact_actual=0,
                author_kind="agent",
                created_by="agent:s3-read-test",
                source_run_id=None,
                reason_code="GENERATED",
                versions=root.versions,
                schema_version=root.schema_version,
                created_at=now,
            ))
            await session.execute(
                update(BranchRow)
                .where(BranchRow.id == first.active_branch_id)
                .values(head_revision_id=revision_id, updated_at=now)
            )
            await session.execute(
                update(ProjectRow)
                .where(ProjectRow.id == first.project_id)
                .values(updated_at=now)
            )

        ai_run = await CreateAIRun(PostgresAIRunUnitOfWork(sessions))(
            CreateAIRunRequest.model_validate({
                "project_id": first.project_id,
                "branch_id": first.active_branch_id,
                "base_revision_id": revision_id,
                "thread_id": f"s3-read-ai-{uuid4().hex}",
                "brief": {
                    "title": "S3 read",
                    "purpose": "Verify recoverable run projection",
                    "style": "synth_ambient",
                    "duration_seconds": 60,
                    "moods": ("calm",),
                },
                "idempotency_key": f"s3-read-ai-{uuid4().hex}",
            })
        )

        media = PostgresMediaJobUnitOfWork(sessions)
        queued = await EnqueueMediaJob(media)(EnqueueMediaJobRequest(
            project_id=first.project_id,
            thread_id=f"s3-read-{uuid4().hex}",
            run_type="parent.generate.v1",
            job_type=MediaJobType.TRANSCODE_EXPORT,
            input_payload={"revision_id": str(revision_id)},
            output_quality_profile=MediaQualityProfile.DELIVERY_MP3_V1,
            idempotency_key=f"delivery-{uuid4().hex}",
        ))
        artifact = AudioArtifact(
            artifact_id=uuid4(), project_id=first.project_id, revision_id=revision_id,
            arrangement_hash=root.content_hash, render_scope=RenderScope.MASTER,
            source_job_id=queued.job_id, content_hash="d" * 64, byte_size=4096,
            storage_key="protected/s3/delivery.mp3", media_role="delivery_master",
            quality_profile=MediaQualityProfile.DELIVERY_MP3_V1, container="mp3",
            codec="mp3", sample_rate_hz=48_000, channels=2, duration_seconds=45.0,
            bitrate_kbps=256, encoder="ffmpeg", encoder_version="7.1",
            lifecycle_class=ArtifactLifecycle.PROTECTED, created_at=now,
        )
        await ApplyWorkerEvent(media)(WorkerEvent(
            event_id=f"s3-read-{uuid4().hex}", job_id=queued.job_id,
            event_type="job.completed", artifact=artifact, occurred_at=now,
        ))

        store = PostgresProjectReadStore(sessions)
        listed = await store.list_projects(limit=50)
        newest_only = await store.list_projects(limit=1)
        workspace = await store.read_project(first.project_id)
        studio = await ReadRevisionStudio(store)(
            project_id=first.project_id, revision_id=revision_id
        )

        listed_project = next(item for item in listed if item.project_id == first.project_id)
        assert newest_only[0].project_id == first.project_id
        assert listed_project.head_revision_id == revision_id
        assert listed_project.has_playable_revision
        assert listed_project.latest_run is not None
        assert listed_project.latest_run.run_id == ai_run.run_id
        assert next(
            index for index, item in enumerate(listed) if item.project_id == first.project_id
        ) < next(index for index, item in enumerate(listed) if item.project_id == other.project_id)
        assert workspace is not None
        assert workspace.head_revision_id == revision_id
        assert workspace.recoverable_run is not None
        assert workspace.recoverable_run.run_id == ai_run.run_id
        assert tuple(item.revision_id for item in workspace.revisions[:2]) == (
            revision_id, first.root_revision_id,
        )
        assert studio.arrangement_ir.project_id == first.project_id
        assert studio.delivery_assets[0].artifact_id == artifact.artifact_id
        assert studio.delivery_assets[0].duration_milliseconds == 45_000
        assert await store.read_revision_studio(
            project_id=other.project_id, revision_id=revision_id
        ) is None

        async with sessions.begin() as session:
            await session.execute(
                update(RevisionRow)
                .where(RevisionRow.id == revision_id)
                .values(arrangement_ir={**root.arrangement_ir, "sample_rate": "48000"})
            )
        with pytest.raises(ApplicationError, match="REVISION_IR_INVALID"):
            await store.read_revision_studio(
                project_id=first.project_id, revision_id=revision_id
            )
    finally:
        await _delete_exact_project(engine, first.project_id)
        await _delete_exact_project(engine, other.project_id)
        await engine.dispose()
