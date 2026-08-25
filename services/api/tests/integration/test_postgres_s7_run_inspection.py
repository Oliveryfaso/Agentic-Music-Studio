from __future__ import annotations

import asyncio
import os
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
from sqlalchemy import text


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


async def _delete_project(engine, project_id: UUID) -> None:  # type: ignore[no-untyped-def]
    async with engine.begin() as connection:
        for statement in (
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
