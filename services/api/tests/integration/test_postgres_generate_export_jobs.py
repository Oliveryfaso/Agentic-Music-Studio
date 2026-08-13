"""Real PostgreSQL boundary for the reusable generated-song export chain."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.composition import (
    PrepareDeterministicCompositionPreview,
    PrepareDeterministicCompositionPreviewRequest,
)
from motif_forge.application.generation import CompleteExportCursor, EnqueueNextCompleteExportJob
from motif_forge.application.media_jobs import EnqueueFollowupMediaJob, EnqueueMediaJob
from motif_forge.application.previews import DecidePreview, DecidePreviewRequest, PreviewDecision
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.media_jobs import MediaJobType
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


async def _delete_exact_project(engine: AsyncEngine, project_id: object) -> None:
    """Delete only rows reachable from this test's exact generated project."""

    async with engine.begin() as connection:
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        statements = (
            "DELETE FROM app.outbox_events WHERE aggregate_id IN "
            "(SELECT id FROM app.jobs WHERE project_id=:project_id) OR aggregate_id IN "
            "(SELECT id FROM app.runs WHERE project_id=:project_id)",
            "DELETE FROM app.job_events WHERE job_id IN "
            "(SELECT id FROM app.jobs WHERE project_id=:project_id)",
            "DELETE FROM app.run_events WHERE run_id IN "
            "(SELECT id FROM app.runs WHERE project_id=:project_id)",
            "DELETE FROM app.jobs WHERE project_id=:project_id",
            "DELETE FROM app.runs WHERE project_id=:project_id",
            "DELETE FROM app.audit_events WHERE project_id=:project_id",
            "DELETE FROM app.approvals WHERE project_id=:project_id",
            "DELETE FROM app.idempotency_records WHERE resource_id=:project_id OR "
            "resource_id IN (SELECT id FROM app.preview_candidates "
            "WHERE project_id=:project_id) OR resource_id IN "
            "(SELECT id FROM app.project_revisions WHERE project_id=:project_id)",
            "DELETE FROM app.preview_candidates WHERE project_id=:project_id",
            "DELETE FROM app.candidate_snapshots WHERE project_id=:project_id",
            "DELETE FROM app.revision_commands WHERE revision_id IN "
            "(SELECT id FROM app.project_revisions WHERE project_id=:project_id)",
            "DELETE FROM app.command_batches WHERE project_id=:project_id",
            "DELETE FROM app.project_branches WHERE project_id=:project_id",
            "DELETE FROM app.project_revisions WHERE project_id=:project_id",
            "DELETE FROM app.projects WHERE id=:project_id",
        )
        for statement in statements:
            await connection.execute(text(statement), {"project_id": project_id})


@pytest.mark.asyncio
async def test_real_postgres_generated_revision_enqueues_one_authoritative_master_job(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    media = PostgresMediaJobUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name=f"Task 6 export {uuid4().hex}",
            actor_id="integration-human",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    preview = await PrepareDeterministicCompositionPreview(projects)(
        PrepareDeterministicCompositionPreviewRequest(
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            seed=20260813,
            actor_id="agent:integration",
            idempotency_key=f"preview-{uuid4().hex}",
        )
    )
    approved = await DecidePreview(projects)(
        DecidePreviewRequest(
            preview_id=preview.preview_id,
            decision=PreviewDecision.APPROVE,
            actor_id="integration-human",
            approval_assertion="I approve this complete export integration fixture.",
            idempotency_key=f"approve-{uuid4().hex}",
        )
    )
    assert approved.revision_id is not None
    cursor = CompleteExportCursor(
        project_id=project.project_id,
        revision_id=approved.revision_id,
        thread_id=f"generate-export-{uuid4().hex}",
        seed=20260813,
    )
    use_case = EnqueueNextCompleteExportJob(
        media,
        enqueue_first=EnqueueMediaJob(media),
        enqueue_followup=EnqueueFollowupMediaJob(media),
    )
    try:
        first = await use_case(cursor)
        replay = await use_case(cursor)

        assert replay.pending_job_id == first.pending_job_id
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT j.job_type, j.input_payload, r.thread_id, "
                        "(SELECT count(*) FROM app.jobs WHERE run_id=r.id) AS job_count, "
                        "(SELECT count(*) FROM app.outbox_events WHERE aggregate_id=j.id "
                        " AND topic='media.job.dispatch.requested') AS dispatch_count "
                        "FROM app.jobs j JOIN app.runs r ON r.id=j.run_id "
                        "WHERE j.id=:job_id"
                    ),
                    {"job_id": first.pending_job_id},
                )
            ).one()
        assert row.job_type == MediaJobType.RENDER_CANONICAL.value
        assert row.input_payload["revision_id"] == str(approved.revision_id)
        assert row.input_payload["arrangement_hash"] == preview.content_hash
        assert row.thread_id == cursor.thread_id
        assert row.job_count == row.dispatch_count == 1
    finally:
        await _delete_exact_project(engine, project.project_id)
        await engine.dispose()
