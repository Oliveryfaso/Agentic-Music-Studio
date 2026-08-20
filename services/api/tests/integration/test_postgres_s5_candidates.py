"""Real PostgreSQL boundary for standalone immutable S5 CandidateSnapshots."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.revisions import VersionRefs, create_candidate_snapshot
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from sqlalchemy import text


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


@pytest.mark.asyncio
async def test_standalone_candidate_snapshot_round_trips_without_revision(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name=f"S5 candidates {uuid4().hex}",
            actor_id="s5-integration",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    snapshot_id = uuid4()
    try:
        async with projects() as transaction:
            base = await transaction.get_revision(project.root_revision_id)
            assert base is not None
            build = build_s1_composition(project.project_id, seed=17)
            snapshot = create_candidate_snapshot(
                base_revision=base,
                candidate_ir=build.arrangement,
                candidate_id=uuid4(),
                commands=build.commands,
                candidate_snapshot_id=snapshot_id,
                source_run_id=None,
                structural_diff=(),
                versions=VersionRefs(compiler="s5-integration.v1"),
                created_at=datetime.now(UTC),
            )
            await transaction.insert_candidate_snapshot(snapshot)
        async with projects() as transaction:
            loaded = await transaction.get_candidate_snapshot(snapshot_id)
        assert loaded == snapshot
        async with engine.connect() as connection:
            revision_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM app.project_revisions "
                    "WHERE project_id=:project_id AND parent_id IS NOT NULL"
                ),
                {"project_id": project.project_id},
            )
        assert revision_count == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM app.candidate_snapshots WHERE project_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.idempotency_records WHERE resource_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.project_branches WHERE project_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.project_revisions WHERE project_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.projects WHERE id=:project_id"),
                {"project_id": project.project_id},
            )
        await engine.dispose()
