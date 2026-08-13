"""Real PostgreSQL proof for approved Plan-to-Revision materialization."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.ai_runs import CreateAIRun, CreateAIRunRequest, RecordAIRunApproval
from motif_forge.application.errors import RevisionConflictError
from motif_forge.application.generation import (
    MaterializeApprovedComposition,
    MaterializeApprovedCompositionRequest,
    PersistPlanningResult,
    PersistPlanningResultRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.tables import BranchRow
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


def _brief() -> CompositionBrief:
    return CompositionBrief(
        title="Polar Current",
        purpose="Instrumental underscore for a quiet orbital observatory",
        style="synth_ambient",
        duration_seconds=120,
        meter="4/4",
        target_bpm=72,
        target_key="D dorian",
        moods=("weightless", "curious"),
        negative_constraints=("no abrupt drop",),
    )


def _plan() -> CompositionPlan:
    return CompositionPlan.model_validate(
        {
            "genre": "synth_ambient",
            "purpose": _brief().purpose,
            "moods": _brief().moods,
            "duration_bars": 36,
            "bpm": 72,
            "meter": "4/4",
            "key": {"tonic": "D", "mode": "dorian"},
            "sections": (
                {
                    "section_id": "opening",
                    "name": "Opening",
                    "start_bar": 0,
                    "end_bar": 8,
                    "function": "Establish the harmonic field",
                    "energy": 0.2,
                },
                {
                    "section_id": "development",
                    "name": "Development",
                    "start_bar": 8,
                    "end_bar": 28,
                    "function": "Develop the pulse and motif",
                    "energy": 0.68,
                },
                {
                    "section_id": "resolution",
                    "name": "Resolution",
                    "start_bar": 28,
                    "end_bar": 36,
                    "function": "Reduce density and resolve",
                    "energy": 0.25,
                },
            ),
            "instrumentation": tuple(
                {
                    "instrument_id": f"layer_{role}",
                    "name": role.title(),
                    "role": role,
                    "pitch_range": "supported built-in range",
                    "entry_section_id": "opening",
                    "exit_section_id": "resolution",
                }
                for role in ("pad", "melody", "bass", "rhythm")
            ),
            "harmonic_language": "Open modal harmony",
            "rhythmic_language": "Sparse pulses",
            "texture": "Layered synthesis",
            "negative_constraints": ("no abrupt drop",),
            "confidence": 0.9,
        },
        strict=True,
    )


async def _delete_exact_project(engine: AsyncEngine, project_id: UUID, run_id: UUID) -> None:
    """Remove only rows reachable from this test's generated project and AI run."""

    async with engine.begin() as connection:
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await connection.execute(
            text("DELETE FROM app.outbox_events WHERE aggregate_id=:run_id"),
            {"run_id": run_id},
        )
        await connection.execute(
            text("DELETE FROM app.ai_runs WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.approvals WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text(
                "DELETE FROM app.idempotency_records WHERE resource_id=:project_id OR "
                "resource_id IN (SELECT id FROM app.preview_candidates "
                "WHERE project_id=:project_id)"
            ),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.preview_candidates WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.candidate_snapshots WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text(
                "DELETE FROM app.revision_commands WHERE revision_id IN "
                "(SELECT id FROM app.project_revisions WHERE project_id=:project_id)"
            ),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.command_batches WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.project_branches WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.project_revisions WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.projects WHERE id=:project_id"),
            {"project_id": project_id},
        )


@pytest.mark.asyncio
async def test_real_postgres_approved_plan_materializes_one_revision_and_replays(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai_runs = PostgresAIRunUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name=f"S2 materialization {uuid4().hex}",
            actor_id="integration-human",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    run = await CreateAIRun(ai_runs)(
        CreateAIRunRequest(
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            thread_id=f"generate-{uuid4().hex}",
            brief=_brief(),
            idempotency_key=f"run-{uuid4().hex}",
        )
    )
    try:
        plan = _plan()
        persist_request = PersistPlanningResultRequest(
            run_id=run.run_id,
            expected_run_version=run.version,
            planning_result={
                "phase": "planning_complete",
                "plan": plan.model_dump(mode="json"),
                "provider_metadata": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "prompt_version": "composition-planner.v1",
                    "schema_version": "composition-plan.v1",
                },
                "counters": {"model_calls": 1, "total_tokens": 900},
            },
        )
        persist = PersistPlanningResult(ai_runs)
        pending = await persist(persist_request)
        pending_replay = await persist(persist_request)
        assert pending_replay == pending
        assertion = "I approve this generated composition after review."
        await RecordAIRunApproval(ai_runs)(
            run_id=run.run_id,
            actor_id="integration-human",
            decision="approve",
            assertion=assertion,
            expected_version=pending.run_version,
            expected_plan_content_hash=pending.plan_hash,
            interrupt_ref=pending.interrupt_ref,
        )
        request = MaterializeApprovedCompositionRequest(
            run_id=run.run_id,
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            plan_id=pending.plan_id,
            expected_plan_hash=pending.plan_hash,
            seed=20260813,
            actor_id="integration-human",
            approval_assertion=assertion,
            idempotency_key=f"materialize-{uuid4().hex}",
        )
        use_case = MaterializeApprovedComposition(ai_runs, projects)

        first = await use_case(request)
        replay = await use_case(request)

        assert first.revision_id is not None
        assert replay.revision_id == first.revision_id
        assert replay.candidate_snapshot_id == first.candidate_snapshot_id
        assert replay.replayed is True
        async with engine.connect() as connection:
            facts = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM app.candidate_snapshots "
                        " WHERE source_run_id=:run_id) AS candidates, "
                        "(SELECT count(*) FROM app.preview_candidates "
                        " WHERE source_run_id=:run_id) AS previews, "
                        "(SELECT count(*) FROM app.project_revisions "
                        " WHERE source_run_id=:run_id) AS revisions, "
                        "(SELECT count(*) FROM app.revision_commands rc JOIN "
                        " app.project_revisions r ON r.id=rc.revision_id "
                        " WHERE r.source_run_id=:run_id) AS commands, "
                        "(SELECT head_revision_id FROM app.project_branches "
                        " WHERE id=:branch_id) AS head"
                    ),
                    {"run_id": run.run_id, "branch_id": project.active_branch_id},
                )
            ).one()
        assert tuple(facts[:4]) == (1, 1, 1, 5)
        assert facts.head == first.revision_id
    finally:
        await _delete_exact_project(engine, project.project_id, run.run_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_branch_change_rolls_back_materialization_transaction(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai_runs = PostgresAIRunUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name=f"S2 conflict {uuid4().hex}",
            actor_id="integration-human",
            idempotency_key=f"project-{uuid4().hex}",
        )
    )
    run = await CreateAIRun(ai_runs)(
        CreateAIRunRequest(
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            thread_id=f"generate-{uuid4().hex}",
            brief=_brief(),
            idempotency_key=f"run-{uuid4().hex}",
        )
    )
    try:
        plan = _plan()
        pending = await PersistPlanningResult(ai_runs)(
            PersistPlanningResultRequest(
                run_id=run.run_id,
                expected_run_version=run.version,
                planning_result={
                    "phase": "planning_complete",
                    "plan": plan.model_dump(mode="json"),
                    "provider_metadata": {
                        "provider": "deterministic",
                        "model": "composition-template",
                        "prompt_version": "none",
                        "schema_version": plan.schema_version,
                    },
                    "counters": {"model_calls": 0, "total_tokens": 0},
                    "fallback_reason": "provider unavailable",
                },
            )
        )
        assertion = "I approve this fallback composition after review."
        await RecordAIRunApproval(ai_runs)(
            run_id=run.run_id,
            actor_id="integration-human",
            decision="approve",
            assertion=assertion,
            expected_version=pending.run_version,
            expected_plan_content_hash=pending.plan_hash,
            interrupt_ref=pending.interrupt_ref,
        )
        async with engine.begin() as connection:
            alternate = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO app.project_revisions "
                    "(id, project_id, parent_id, created_on_branch_id, arrangement_ir, "
                    "content_hash, change_impact_predicted, change_impact_actual, author_kind, "
                    "created_by, reason_code, versions, schema_version, created_at) "
                    "SELECT :alternate, project_id, id, created_on_branch_id, arrangement_ir, "
                    "content_hash, 0, 0, 'human', 'integration-human', 'CONCURRENT_EDIT', "
                    "versions, schema_version, now() FROM app.project_revisions WHERE id=:root"
                ),
                {"alternate": alternate, "root": project.root_revision_id},
            )
            await connection.execute(
                update(BranchRow)
                .where(BranchRow.id == project.active_branch_id)
                .values(head_revision_id=alternate)
            )
        request = MaterializeApprovedCompositionRequest(
            run_id=run.run_id,
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            plan_id=pending.plan_id,
            expected_plan_hash=pending.plan_hash,
            seed=20260813,
            actor_id="integration-human",
            approval_assertion=assertion,
            idempotency_key=f"materialize-{uuid4().hex}",
        )

        with pytest.raises(RevisionConflictError):
            await MaterializeApprovedComposition(ai_runs, projects)(request)

        async with engine.connect() as connection:
            counts = (
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
                    {"run_id": run.run_id},
                )
            ).one()
        assert tuple(counts) == (0, 0, 0)
    finally:
        await _delete_exact_project(engine, project.project_id, run.run_id)
        await engine.dispose()
