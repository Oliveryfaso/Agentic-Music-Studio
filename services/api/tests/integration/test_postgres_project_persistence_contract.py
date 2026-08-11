from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config
from motif_forge.application.errors import ChangeImpactEscalatedError, RevisionConflictError
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.domain.commands import AddTrackCommand, AddTrackPayload
from motif_forge.domain.ir import Track, TrackRole, TrackType
from motif_forge.domain.revisions import AuthorKind, ChangeImpact
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.tables import (
    AuditEventRow,
    BranchRow,
    CommandBatchRow,
    IdempotencyRow,
    ProjectRow,
    RevisionCommandRow,
    RevisionRow,
)
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine


def _upgrade_database(dsn: str) -> None:
    project_root = Path(__file__).resolve().parents[4]
    config = Config(project_root / "alembic.ini")
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        alembic_command.upgrade(config, "head")


@pytest_asyncio.fixture
async def persistence_engine(test_postgres_dsn: str) -> AsyncIterator[AsyncEngine]:
    """Upgrade and connect only to the explicitly opted-in PostgreSQL test database."""

    await asyncio.to_thread(_upgrade_database, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


def _add_track(
    actor_kind: Literal["human", "agent", "system"] = "human",
) -> AddTrackCommand:
    return AddTrackCommand(
        command_id=uuid4(),
        actor_kind=actor_kind,
        client_sequence=0,
        payload=AddTrackPayload(
            track=Track(
                track_id=uuid4(),
                track_type=TrackType.INSTRUMENT,
                name="Integration Keys",
                role=TrackRole.HARMONY,
                instrument_ref="builtin:piano",
            )
        ),
    )


async def _delete_exact_project(engine: AsyncEngine, project_id: UUID) -> None:
    """Remove only rows reachable from the one project created by this test."""

    revision_ids = select(RevisionRow.id).where(RevisionRow.project_id == project_id)
    async with engine.begin() as connection:
        # The project/root Revision/main Branch form intentional deferred FK cycles.
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await connection.execute(
            delete(AuditEventRow).where(AuditEventRow.project_id == project_id)
        )
        await connection.execute(
            delete(RevisionCommandRow).where(RevisionCommandRow.revision_id.in_(revision_ids))
        )
        await connection.execute(
            delete(IdempotencyRow).where(
                IdempotencyRow.resource_id.in_(
                    select(RevisionRow.id).where(RevisionRow.project_id == project_id)
                )
                | (IdempotencyRow.resource_id == project_id)
            )
        )
        await connection.execute(
            delete(CommandBatchRow).where(CommandBatchRow.project_id == project_id)
        )
        await connection.execute(delete(BranchRow).where(BranchRow.project_id == project_id))
        await connection.execute(delete(RevisionRow).where(RevisionRow.project_id == project_id))
        await connection.execute(delete(ProjectRow).where(ProjectRow.id == project_id))


@pytest.mark.asyncio
async def test_root_commit_idempotency_and_stale_head_conflict_use_real_postgres(
    persistence_engine: AsyncEngine,
) -> None:
    """Exercise transaction commit, replay, and optimistic conflict against PostgreSQL."""

    uow = PostgresUnitOfWork(create_session_factory(persistence_engine))
    create_request = CreateProjectRequest(
        name="PostgreSQL Integration Project",
        actor_id="integration-test",
        idempotency_key=f"create-{uuid4().hex}",
    )

    created = await CreateProject(uow)(create_request)
    try:
        replayed_create = await CreateProject(uow)(create_request)
        assert replayed_create.project_id == created.project_id
        assert replayed_create.root_revision_id == created.root_revision_id
        assert replayed_create.replayed is True

        commit_request = CommitCommandBatchRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=created.root_revision_id,
            commands=(_add_track(),),
            actor_id="integration-test",
            author_kind=AuthorKind.HUMAN,
            reason="TRACK_ADDED",
            idempotency_key=f"commit-{uuid4().hex}",
        )
        commit_use_case = CommitCommandBatch(uow)
        committed = await commit_use_case(commit_request)
        replayed_commit = await commit_use_case(commit_request)

        assert committed.actual_change_impact is ChangeImpact.L1
        assert replayed_commit.revision_id == committed.revision_id
        assert replayed_commit.replayed is True

        stale_request = CommitCommandBatchRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=created.root_revision_id,
            commands=(_add_track(),),
            actor_id="integration-test",
            author_kind=AuthorKind.HUMAN,
            reason="STALE_TRACK_ADDED",
            idempotency_key=f"stale-{uuid4().hex}",
        )
        with pytest.raises(RevisionConflictError) as raised:
            await commit_use_case(stale_request)

        assert raised.value.code == "REVISION_CONFLICT"
        assert raised.value.current_revision_id == committed.revision_id

        l2_request = CommitCommandBatchRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=committed.revision_id,
            commands=(_add_track("agent"),),
            actor_id="integration-planner",
            author_kind=AuthorKind.AGENT,
            reason="AI_TRACK_ADDED",
            idempotency_key=f"l2-{uuid4().hex}",
        )
        with pytest.raises(ChangeImpactEscalatedError) as escalated:
            await commit_use_case(l2_request)

        assert escalated.value.code == "CHANGE_IMPACT_ESCALATED"

        async with persistence_engine.connect() as connection:
            branch_head = await connection.scalar(
                select(BranchRow.head_revision_id).where(BranchRow.id == created.active_branch_id)
            )
            revision_count = await connection.scalar(
                select(func.count())
                .select_from(RevisionRow)
                .where(RevisionRow.project_id == created.project_id)
            )
            command_count = await connection.scalar(
                select(func.count())
                .select_from(RevisionCommandRow)
                .where(RevisionCommandRow.revision_id == committed.revision_id)
            )

        assert branch_head == committed.revision_id
        assert revision_count == 2
        assert command_count == 1
    finally:
        await _delete_exact_project(persistence_engine, created.project_id)
