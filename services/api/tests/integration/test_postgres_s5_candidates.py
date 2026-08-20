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
from motif_forge.application.generation_candidates import (
    CreateCandidateSelectionPreview,
    CreateCandidateSelectionPreviewRequest,
    CreateCompositionCandidate,
    CreateCompositionCandidateRequest,
    MaterializeSelectedCompositionCandidate,
    MaterializeSelectedCompositionCandidateRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.candidates import CandidateLabel, derive_candidate_seed
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.revisions import VersionRefs, create_candidate_snapshot
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.generation import (
    PostgresCompositionMaterializationUnitOfWork,
)
from sqlalchemy import text

from .test_postgres_generate_materialization import (
    _approved_materialization_fixture,
    _delete_exact_project,
)


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


@pytest.mark.asyncio
async def test_two_candidates_persist_before_one_selected_revision_and_replay(
    test_postgres_dsn: str,
) -> None:
    engine, sessions, _, _, approved = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    uow = PostgresCompositionMaterializationUnitOfWork(sessions)
    try:
        create = CreateCompositionCandidate(uow)
        candidates = [
            await create(
                CreateCompositionCandidateRequest(
                    run_id=approved.run_id,
                    project_id=approved.project_id,
                    branch_id=approved.branch_id,
                    base_revision_id=approved.base_revision_id,
                    plan_id=approved.plan_id,
                    expected_plan_hash=approved.expected_plan_hash,
                    label=label,
                    seed=derive_candidate_seed(0, label),
                )
            )
            for label in (CandidateLabel.A, CandidateLabel.B)
        ]
        preview_service = CreateCandidateSelectionPreview(uow)
        previews = [
            await preview_service(
                CreateCandidateSelectionPreviewRequest(
                    run_id=approved.run_id,
                    project_id=approved.project_id,
                    branch_id=approved.branch_id,
                    base_revision_id=approved.base_revision_id,
                    candidate_snapshot_id=candidate.candidate_snapshot_id,
                    preview_artifact_id=uuid4(),
                    evidence_refs=(f"candidate:{candidate.label.value}:preview",),
                )
            )
            for candidate in candidates
        ]
        async with engine.connect() as connection:
            before = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM app.candidate_snapshots "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.preview_candidates "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.project_revisions "
                        " WHERE source_run_id=:run_id)"
                    ),
                    {"run_id": approved.run_id},
                )
            ).one()
        assert tuple(before) == (2, 2, 0)

        selected = candidates[1]
        request = MaterializeSelectedCompositionCandidateRequest(
            run_id=approved.run_id,
            project_id=approved.project_id,
            branch_id=approved.branch_id,
            base_revision_id=approved.base_revision_id,
            plan_id=approved.plan_id,
            expected_plan_hash=approved.expected_plan_hash,
            selected_preview_id=previews[1].preview_id,
            expected_candidate_content_hash=selected.candidate_content_hash,
            seed=selected.seed,
            actor_id=approved.actor_id,
            selection_assertion="I select candidate B after comparing both previews.",
            idempotency_key=f"s5-select-{uuid4().hex}",
        )
        materialize = MaterializeSelectedCompositionCandidate(uow)
        first = await materialize(request)
        replay = await materialize(request)

        assert replay.replayed is True
        assert replay.revision_id == first.revision_id
        async with engine.connect() as connection:
            after = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM app.candidate_snapshots "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.preview_candidates "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.project_revisions "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.composition_materialization_receipts "
                        " WHERE run_id=:run_id), "
                        "(SELECT head_revision_id FROM app.project_branches WHERE id=:branch_id)"
                    ),
                    {"run_id": approved.run_id, "branch_id": approved.branch_id},
                )
            ).one()
        assert tuple(after[:4]) == (2, 2, 1, 1)
        assert after[4] == first.revision_id
    finally:
        await _delete_exact_project(engine, approved.project_id, approved.run_id)
        await engine.dispose()
