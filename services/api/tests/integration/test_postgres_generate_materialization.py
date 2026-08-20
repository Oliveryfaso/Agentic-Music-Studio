"""Real PostgreSQL proof for approved Plan-to-Revision materialization."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Literal
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.ai_runs import (
    CreateAIRun,
    CreateAIRunRequest,
    MarkAIRunPlanPending,
    PersistCompositionPlan,
    ReadAIRun,
    RecordAIRunApproval,
)
from motif_forge.application.errors import ApplicationError, RevisionConflictError
from motif_forge.application.generation import (
    MaterializeApprovedComposition,
    MaterializeApprovedCompositionRequest,
    PersistPlanningResult,
    PersistPlanningResultRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V1,
    PersistedCompositionPlan,
    composition_plan_content_hash,
)
from motif_forge.domain.revisions import CandidateSnapshot, PreviewCandidate
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.generation import (
    PostgresCompositionMaterializationTransaction,
    PostgresCompositionMaterializationUnitOfWork,
)
from motif_forge.infrastructure.persistence.tables import BranchRow
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


def _downgrade(dsn: str, revision: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.downgrade(Config(root / "alembic.ini"), revision)


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


def _plan(*, development_energy: float = 0.68) -> CompositionPlan:
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
                    "energy": development_energy,
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
            text("DELETE FROM app.composition_materialization_receipts WHERE run_id=:run_id"),
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


async def _approved_materialization_fixture(
    test_postgres_dsn: str,
    *,
    decision: Literal["approve", "reject"] = "approve",
) -> tuple[
    AsyncEngine,
    SessionFactory,
    PostgresUnitOfWork,
    PostgresAIRunUnitOfWork,
    MaterializeApprovedCompositionRequest,
]:
    """Create one public-path approved Plan without bypassing Run contracts."""

    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai_runs = PostgresAIRunUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name=f"S2 transaction {uuid4().hex}",
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
    plan = _plan()
    pending = await PersistPlanningResult(ai_runs)(
        PersistPlanningResultRequest(
            run_id=run.run_id,
            expected_run_version=run.version,
            planning_result={
                "phase": "planning_complete",
                "plan": plan.model_dump(mode="json"),
                "provider_metadata": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "prompt_version": "composition-planner.v1",
                    "schema_version": plan.schema_version,
                },
                "counters": {"model_calls": 1, "total_tokens": 900},
            },
        )
    )
    assertion = "I approve this generated composition after review."
    await RecordAIRunApproval(ai_runs)(
        run_id=run.run_id,
        actor_id="integration-human",
        decision=decision,
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
    return engine, sessions, projects, ai_runs, request


async def _materialization_counts(engine: AsyncEngine, run_id: UUID) -> tuple[int, ...]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM app.candidate_snapshots WHERE source_run_id=:run_id), "
                    "(SELECT count(*) FROM app.preview_candidates WHERE source_run_id=:run_id), "
                    "(SELECT count(*) FROM app.project_revisions WHERE source_run_id=:run_id), "
                    "(SELECT count(*) FROM app.composition_materialization_receipts "
                    " WHERE run_id=:run_id), "
                    "(SELECT count(*) FROM app.ai_run_events WHERE run_id=:run_id "
                    " AND event_type='composition.materialized')"
                ),
                {"run_id": run_id},
            )
        ).one()
    return tuple(row)


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
        use_case = MaterializeApprovedComposition(
            PostgresCompositionMaterializationUnitOfWork(sessions),
        )

        first = await use_case(request)
        replay = await use_case(request)

        assert first.revision_id is not None
        assert replay.revision_id == first.revision_id
        assert replay.candidate_snapshot_id == first.candidate_snapshot_id
        assert replay.replayed is True
        assert first.receipt_id is not None
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
                        " WHERE id=:branch_id) AS head, "
                        "(SELECT count(*) FROM app.composition_materialization_receipts "
                        " WHERE run_id=:run_id) AS receipts, "
                        "(SELECT count(*) FROM app.ai_run_events WHERE run_id=:run_id "
                        " AND event_type='composition.materialized') AS events"
                    ),
                    {"run_id": run.run_id, "branch_id": project.active_branch_id},
                )
            ).one()
        assert tuple(facts[:4]) == (1, 1, 1, 5)
        assert facts.head == first.revision_id
        assert facts.receipts == facts.events == 1
        async with engine.connect() as connection:
            receipt = (
                await connection.execute(
                    text(
                        "SELECT id, schema_version, run_id, plan_id, plan_content_hash, "
                        "plan_hash_version, seed, actor_id, "
                        "assertion_hash, candidate_snapshot_id, preview_id, revision_id, "
                        "command_batch_id, style_pack_version, compiler_version "
                        "FROM app.composition_materialization_receipts WHERE run_id=:run_id"
                    ),
                    {"run_id": run.run_id},
                )
            ).one()
            event = (
                await connection.execute(
                    text(
                        "SELECT payload FROM app.ai_run_events WHERE run_id=:run_id "
                        "AND event_type='composition.materialized'"
                    ),
                    {"run_id": run.run_id},
                )
            ).scalar_one()
            candidate_versions = (
                await connection.execute(
                    text(
                        "SELECT versions FROM app.candidate_snapshots "
                        "WHERE id=:candidate_snapshot_id"
                    ),
                    {"candidate_snapshot_id": first.candidate_snapshot_id},
                )
            ).scalar_one()
            revision_versions = (
                await connection.execute(
                    text("SELECT versions FROM app.project_revisions WHERE id=:revision_id"),
                    {"revision_id": first.revision_id},
                )
            ).scalar_one()
            command_facts = (
                await connection.execute(
                    text(
                        "SELECT client_sequence, command_type, payload FROM app.revision_commands "
                        "WHERE revision_id=:revision_id ORDER BY client_sequence"
                    ),
                    {"revision_id": first.revision_id},
                )
            ).all()
        assert receipt.id == first.receipt_id
        assert receipt.schema_version == "composition-materialization-receipt.v1"
        assert receipt.run_id == run.run_id
        assert receipt.plan_id == pending.plan_id
        assert receipt.plan_content_hash == pending.plan_hash
        assert receipt.plan_hash_version == pending.hash_version
        assert receipt.seed == request.seed
        assert receipt.actor_id == request.actor_id
        assert receipt.assertion_hash != request.approval_assertion
        assert receipt.candidate_snapshot_id == first.candidate_snapshot_id
        assert receipt.preview_id == first.preview_id
        assert receipt.revision_id == first.revision_id
        assert receipt.style_pack_version == "style:synth-ambient:v1"
        assert receipt.compiler_version == "synth-ambient-compiler.v1"
        assert event == {
            "receipt_id": str(receipt.id),
            "receipt_schema_version": "composition-materialization-receipt.v1",
            "plan_id": str(pending.plan_id),
            "plan_hash": pending.plan_hash,
            "plan_hash_version": pending.hash_version,
            "seed": request.seed,
            "candidate_snapshot_id": str(first.candidate_snapshot_id),
            "preview_id": str(first.preview_id),
            "revision_id": str(first.revision_id),
            "command_batch_id": str(receipt.command_batch_id),
            "style_pack_version": "style:synth-ambient:v1",
            "compiler_version": "synth-ambient-compiler.v1",
            "theory_report": {
                "schema_version": "theory-report.v1",
                "engine_version": "theory-engine.v1",
                "pack_id": "style:synth-ambient:v1",
                "issues": [],
            },
        }
        assert candidate_versions == revision_versions
        assert candidate_versions["knowledge"] == "style:synth-ambient:v1"
        assert candidate_versions["compiler"] == "synth-ambient-compiler.v1"
        assert [row.client_sequence for row in command_facts] == [0, 1, 2, 3, 4]
        assert [row.command_type for row in command_facts] == [
            "initialize_composition",
            "add_track",
            "add_track",
            "add_track",
            "add_track",
        ]
        provenance = command_facts[0].payload["provenance"]
        assert {entry["version"] for entry in provenance} >= {
            "composition-plan.v1",
            "v1",
            "synth-ambient-compiler.v1",
        }
        assert "style:synth-ambient:v1" in {entry["ref"] for entry in provenance}
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
            await MaterializeApprovedComposition(
                PostgresCompositionMaterializationUnitOfWork(sessions),
            )(request)

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


@pytest.mark.asyncio
async def test_real_postgres_plan_pending_is_atomic_and_concurrent_replay_is_exact(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai_runs = PostgresAIRunUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name=f"S2 plan transaction {uuid4().hex}",
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
    request = PersistPlanningResultRequest(
        run_id=run.run_id,
        expected_run_version=run.version,
        planning_result={
            "phase": "planning_complete",
            "plan": _plan().model_dump(mode="json"),
            "provider_metadata": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "prompt_version": "composition-planner.v1",
                "schema_version": "composition-plan.v1",
            },
            "counters": {"model_calls": 1, "total_tokens": 900},
        },
    )
    try:
        with pytest.raises(ApplicationError, match="AI_RUN_VERSION_CONFLICT"):
            await PersistPlanningResult(ai_runs)(
                request.model_copy(update={"expected_run_version": run.version + 1})
            )
        async with engine.connect() as connection:
            after_failure = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM app.composition_plans WHERE run_id=:run_id), "
                        "status, version, pending_plan_id, pending_plan_content_hash, "
                        "pending_interrupt_ref FROM app.ai_runs WHERE id=:run_id"
                    ),
                    {"run_id": run.run_id},
                )
            ).one()
        assert after_failure == (0, "queued", 0, None, None, None)

        first, second = await asyncio.gather(
            PersistPlanningResult(ai_runs)(request),
            PersistPlanningResult(ai_runs)(request),
        )
        assert first == second
        async with engine.connect() as connection:
            exact = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM app.composition_plans WHERE run_id=:run_id), "
                        "(SELECT count(*) FROM app.ai_run_events WHERE run_id=:run_id), "
                        "(SELECT count(*) FROM app.outbox_events WHERE aggregate_id=:run_id), "
                        "status, version, pending_plan_id, pending_plan_content_hash, "
                        "pending_interrupt_ref FROM app.ai_runs WHERE id=:run_id"
                    ),
                    {"run_id": run.run_id},
                )
            ).one()
        assert exact[:5] == (1, 1, 1, "waiting_approval", 1)
        assert exact[5:] == (first.plan_id, first.plan_hash, first.interrupt_ref)
    finally:
        await _delete_exact_project(engine, project.project_id, run.run_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_cancel_wins_run_lock_before_materialization(
    test_postgres_dsn: str,
) -> None:
    engine, sessions, _projects, ai_runs, request = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    cancel_transaction = ai_runs()
    await cancel_transaction.__aenter__()
    try:
        live = await cancel_transaction.read_ai_run(request.run_id)
        cancel = asyncio.create_task(
            cancel_transaction.request_ai_run_action(
                run_id=request.run_id,
                action="cancel",
                expected_version=live.version,
                idempotency_key=f"cancel-{uuid4().hex}",
                outbox_event_id=uuid4(),
                now=live.updated_at,
            )
        )
        cancelled = await cancel
        materialize = asyncio.create_task(
            MaterializeApprovedComposition(
                PostgresCompositionMaterializationUnitOfWork(sessions),
            )(request)
        )
        await asyncio.sleep(0)
        assert not materialize.done()
        await cancel_transaction.__aexit__(None, None, None)
        with pytest.raises(ApplicationError, match="AI_RUN_APPROVAL_CONFLICT"):
            await materialize
        assert cancelled.status.value == "cancelled"
        assert (await ReadAIRun(ai_runs)(request.run_id)).status.value == "cancelled"
        assert await _materialization_counts(engine, request.run_id) == (0, 0, 0, 0, 0)
    finally:
        if cancel_transaction._session.in_transaction():  # type: ignore[attr-defined]
            await cancel_transaction.__aexit__(RuntimeError, RuntimeError(), None)
        await _delete_exact_project(engine, request.project_id, request.run_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_rejection_uses_atomic_authority_and_creates_no_writes(
    test_postgres_dsn: str,
) -> None:
    engine, sessions, _projects, _ai_runs, request = await _approved_materialization_fixture(
        test_postgres_dsn,
        decision="reject",
    )
    compiler = Mock(side_effect=AssertionError("compiler must not run"))
    try:
        result = await MaterializeApprovedComposition(
            PostgresCompositionMaterializationUnitOfWork(sessions),
            compiler=compiler,
        )(request)

        assert result.status == "rejected"
        compiler.assert_not_called()
        assert await _materialization_counts(engine, request.run_id) == (0, 0, 0, 0, 0)
    finally:
        await _delete_exact_project(engine, request.project_id, request.run_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_concurrent_caller_keys_share_one_durable_receipt(
    test_postgres_dsn: str,
) -> None:
    engine, sessions, _projects, _ai_runs, request = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    try:
        use_case = MaterializeApprovedComposition(
            PostgresCompositionMaterializationUnitOfWork(sessions),
        )
        first, second = await asyncio.gather(
            use_case(request.model_copy(update={"idempotency_key": f"caller-a-{uuid4().hex}"})),
            use_case(request.model_copy(update={"idempotency_key": f"caller-b-{uuid4().hex}"})),
        )
        assert first.receipt_id == second.receipt_id
        assert first.candidate_snapshot_id == second.candidate_snapshot_id
        assert first.preview_id == second.preview_id
        assert first.revision_id == second.revision_id
        assert {first.replayed, second.replayed} == {False, True}
        assert await _materialization_counts(engine, request.run_id) == (1, 1, 1, 1, 1)
    finally:
        await _delete_exact_project(engine, request.project_id, request.run_id)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("corruption_sql", "error_code"),
    [
        (
            "UPDATE app.composition_plans SET plan=jsonb_set(plan, '{bpm}', "
            "to_jsonb('72'::text)) WHERE id=:plan_id",
            "PLAN_INTEGRITY_ERROR",
        ),
        (
            "UPDATE app.composition_plans SET style_pack_version='unsupported-style.v1' "
            "WHERE id=:plan_id",
            "PLAN_IDENTITY_MISMATCH",
        ),
    ],
)
async def test_real_postgres_corrupt_plan_identity_fails_before_materialization(
    test_postgres_dsn: str,
    corruption_sql: str,
    error_code: str,
) -> None:
    engine, sessions, _projects, _ai_runs, request = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(corruption_sql),
                {"plan_id": request.plan_id},
            )
        with pytest.raises(ApplicationError, match=error_code):
            await MaterializeApprovedComposition(
                PostgresCompositionMaterializationUnitOfWork(sessions),
            )(request)
        assert await _materialization_counts(engine, request.run_id) == (0, 0, 0, 0, 0)
    finally:
        await _delete_exact_project(engine, request.project_id, request.run_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_lossy_v1_plan_is_rejected_before_compiler_or_writes(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai_runs = PostgresAIRunUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name=f"S2 legacy hash guard {uuid4().hex}",
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
        plan = _plan(development_energy=0.2500001)
        plan_hash = composition_plan_content_hash(plan, hash_version=PLAN_HASH_VERSION_V1)
        persisted = PersistedCompositionPlan(
            plan_id=uuid4(),
            run_id=run.run_id,
            plan=plan,
            content_hash=plan_hash,
            hash_version=PLAN_HASH_VERSION_V1,
            provider="legacy",
            model="legacy-rounded-planner",
            prompt_version="composition-planner.v0",
            schema_version=plan.schema_version,
            style_pack_version="synth-ambient.v1",
        )
        await PersistCompositionPlan(ai_runs)(persisted)
        pending = await MarkAIRunPlanPending(ai_runs)(
            run_id=run.run_id,
            plan_id=persisted.plan_id,
            expected_version=run.version,
        )
        assert pending.pending_interrupt_ref is not None
        assertion = "I approve this legacy composition after review."
        await RecordAIRunApproval(ai_runs)(
            run_id=run.run_id,
            actor_id="integration-human",
            decision="approve",
            assertion=assertion,
            expected_version=pending.version,
            expected_plan_content_hash=plan_hash,
            interrupt_ref=pending.pending_interrupt_ref,
        )
        request = MaterializeApprovedCompositionRequest(
            run_id=run.run_id,
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            plan_id=persisted.plan_id,
            expected_plan_hash=plan_hash,
            seed=20260813,
            actor_id="integration-human",
            approval_assertion=assertion,
            idempotency_key=f"materialize-{uuid4().hex}",
        )
        compiler = Mock(side_effect=AssertionError("compiler must not run"))

        with pytest.raises(ApplicationError, match="PLAN_HASH_VERSION_UNSAFE"):
            await MaterializeApprovedComposition(
                PostgresCompositionMaterializationUnitOfWork(sessions),
                compiler=compiler,
            )(request)

        compiler.assert_not_called()
        assert await _materialization_counts(engine, run.run_id) == (0, 0, 0, 0, 0)
    finally:
        await _delete_exact_project(engine, project.project_id, run.run_id)
        await engine.dispose()


class _BranchAdvanceAfterPreviewTransaction(PostgresCompositionMaterializationTransaction):
    def __init__(self, sessions: SessionFactory, alternate_revision_id: UUID) -> None:
        super().__init__(sessions())
        self._alternate_revision_id = alternate_revision_id

    async def insert_candidate_preview(
        self, *, snapshot: CandidateSnapshot, preview: PreviewCandidate
    ) -> None:
        await super().insert_candidate_preview(snapshot=snapshot, preview=preview)
        await self._session.execute(
            update(BranchRow)
            .where(BranchRow.id == preview.branch_id)
            .values(head_revision_id=self._alternate_revision_id)
        )


class _ReceiptFailureTransaction(PostgresCompositionMaterializationTransaction):
    async def insert_materialization_receipt(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("injected receipt write failure")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["branch_after_preview", "receipt_write"])
async def test_real_postgres_composite_materialization_rolls_back_every_write(
    test_postgres_dsn: str,
    failure: str,
) -> None:
    engine, sessions, _projects, _ai_runs, request = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    alternate = uuid4()
    try:
        async with engine.begin() as connection:
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
                {"alternate": alternate, "root": request.base_revision_id},
            )
        if failure == "branch_after_preview":

            def factory() -> PostgresCompositionMaterializationTransaction:
                return _BranchAdvanceAfterPreviewTransaction(sessions, alternate)

            expected_error = RevisionConflictError
        else:

            def factory() -> PostgresCompositionMaterializationTransaction:
                return _ReceiptFailureTransaction(sessions())

            expected_error = RuntimeError
        with pytest.raises(expected_error):
            await MaterializeApprovedComposition(
                factory,
            )(request)
        assert await _materialization_counts(engine, request.run_id) == (0, 0, 0, 0, 0)
        async with engine.connect() as connection:
            head = await connection.scalar(
                text("SELECT head_revision_id FROM app.project_branches WHERE id=:branch_id"),
                {"branch_id": request.branch_id},
            )
        assert head == request.base_revision_id
    finally:
        await _delete_exact_project(engine, request.project_id, request.run_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_0017_and_0016_downgrade_refuse_receipts_then_round_trip_when_empty(
    test_postgres_dsn: str,
) -> None:
    engine, sessions, _projects, _ai_runs, request = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    try:
        await MaterializeApprovedComposition(
            PostgresCompositionMaterializationUnitOfWork(sessions),
        )(request)
        with pytest.raises(RuntimeError, match=r"cannot downgrade 0017.*receipts exist"):
            await asyncio.to_thread(_downgrade, test_postgres_dsn, "20260813_0015")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260820_0017"
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM app.composition_materialization_receipts "
                        "WHERE run_id=:run_id"
                    ),
                    {"run_id": request.run_id},
                )
                == 1
            )
        await _delete_exact_project(engine, request.project_id, request.run_id)
        await engine.dispose()
        await asyncio.to_thread(_downgrade, test_postgres_dsn, "20260813_0015")
        downgraded = create_postgres_engine(test_postgres_dsn)
        async with downgraded.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT to_regclass('app.composition_materialization_receipts')")
                )
                is None
            )
        await downgraded.dispose()
        await asyncio.to_thread(_upgrade, test_postgres_dsn)
    finally:
        await engine.dispose()
