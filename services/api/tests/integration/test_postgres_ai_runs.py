"""Real PostgreSQL coverage for the S2 durable AI-run ledger."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.agent.schemas import (
    CompositionBrief,
    CompositionPlan,
    InstrumentPlan,
    KeyPlan,
    SectionPlan,
)
from motif_forge.application.ai_runs import (
    CreateAIRun,
    CreateAIRunRequest,
    ListAIRunEvents,
    PersistCompositionPlan,
    RecordAIRunApproval,
    RecordAIRunEvent,
    RecordModelUsage,
    RequestAIRunAction,
    ReserveModelRequest,
)
from motif_forge.application.errors import ApplicationError
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.ai_runs import (
    AIRunEvent,
    AIRunStatus,
    ModelRequestKind,
    PersistedCompositionPlan,
    composition_plan_content_hash,
)
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.tables import AIRunApprovalRow, AIRunRow
from sqlalchemy import func, select, text


def _upgrade(dsn: str, revision: str = "head") -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), revision)


def _downgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.downgrade(Config(root / "alembic.ini"), "-1")


def _brief() -> CompositionBrief:
    return CompositionBrief(
        title="S2 Test",
        purpose="An instrumental integration test",
        style="synth_ambient",
        duration_seconds=60,
        moods=("calm",),
    )


def _plan() -> CompositionPlan:
    return CompositionPlan(
        genre="synth_ambient",
        purpose="An instrumental integration test",
        moods=("calm",),
        duration_bars=8,
        bpm=80,
        meter="4/4",
        key=KeyPlan(tonic="C", mode="major"),
        sections=(
            SectionPlan(
                section_id="intro",
                name="Intro",
                start_bar=0,
                end_bar=4,
                function="open",
                energy=0.2,
            ),
            SectionPlan(
                section_id="end", name="End", start_bar=4, end_bar=8, function="close", energy=0.4
            ),
        ),
        instrumentation=(
            InstrumentPlan(
                instrument_id="pad",
                name="Pad",
                role="harmony",
                pitch_range="C3-C5",
                entry_section_id="intro",
                exit_section_id="end",
            ),
        ),
        harmonic_language="diatonic",
        rhythmic_language="slow",
        texture="pad",
        confidence=0.8,
    )


async def _seed_run(
    dsn: str, *, key: str = "s2-ai-run-key"
) -> tuple[UUID, UUID, UUID, PostgresAIRunUnitOfWork]:
    engine = create_postgres_engine(dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name=f"S2 {uuid4().hex}", actor_id="s2-test", idempotency_key=f"project-{uuid4().hex}"
        )
    )
    run_uow = PostgresAIRunUnitOfWork(sessions)
    run = await CreateAIRun(run_uow)(
        CreateAIRunRequest(
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            thread_id=f"generate-{uuid4().hex}",
            brief=_brief(),
            idempotency_key=key,
        )
    )
    return run.run_id, project.project_id, project.root_revision_id, run_uow


@pytest.mark.asyncio
async def test_create_replay_plan_events_approval_actions_and_ledger(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow = await _seed_run(test_postgres_dsn)
    replay = await CreateAIRun(uow)(
        CreateAIRunRequest(
            project_id=project_id,
            branch_id=(await _run(uow, run_id)).branch_id,
            base_revision_id=(await _run(uow, run_id)).base_revision_id,
            thread_id=(await _run(uow, run_id)).thread_id,
            brief=_brief(),
            idempotency_key="s2-ai-run-key",
        )
    )
    assert replay.run_id == run_id
    plan = _plan()
    stored = PersistedCompositionPlan(
        plan_id=uuid4(),
        run_id=run_id,
        plan=plan,
        content_hash=composition_plan_content_hash(plan),
        provider="fallback",
        model="deterministic",
        prompt_version="p1",
        schema_version="composition-plan.v1",
        style_pack_version="s1",
    )
    assert (await PersistCompositionPlan(uow)(stored)).plan_id == stored.plan_id
    with pytest.raises(ApplicationError, match="PLAN_PROVENANCE_CONFLICT"):
        await PersistCompositionPlan(uow)(stored.model_copy(update={"provider": "other"}))
    event = await RecordAIRunEvent(uow)(
        AIRunEvent(
            sequence=1,
            event_id=uuid4(),
            run_id=run_id,
            event_type="model.completed",
            phase="planning",
            payload={"prompt_tokens": 4, "completion_tokens": 2},
            dedupe_key="usage",
        )
    )
    replay_event = await RecordAIRunEvent(uow)(
        event.model_copy(update={"event_id": uuid4(), "sequence": 1})
    )
    assert replay_event.sequence == event.sequence
    events = await ListAIRunEvents(uow)(run_id)
    assert [item.sequence for item in events] == sorted(item.sequence for item in events)
    async with uow() as transaction:
        await transaction._session.execute(
            text("UPDATE app.ai_runs SET status = 'waiting_approval', version = 1 WHERE id = :id"),
            {"id": run_id},
        )  # type: ignore[attr-defined]
    approval = await RecordAIRunApproval(uow)(
        run_id=run_id,
        actor_id="human",
        decision="approve",
        assertion="I approve after review",
        expected_version=1,
    )
    assert approval.assertion_hash != "I approve after review"
    async with uow() as transaction:
        stored_hash = await transaction._session.scalar(  # type: ignore[attr-defined]
            select(AIRunApprovalRow.assertion_hash).where(AIRunApprovalRow.run_id == run_id)
        )
    assert stored_hash == approval.assertion_hash
    approved_replay = await RecordAIRunApproval(uow)(
        run_id=run_id,
        actor_id="human",
        decision="approve",
        assertion="I approve after review",
        expected_version=1,
    )
    assert approved_replay.approval_id == approval.approval_id
    reservation = await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.INITIAL)
    observed = await RecordModelUsage(uow)(
        run_id=run_id,
        reservation_id=reservation.reservation_id,
        provider_operation_id="provider-op-1",
        prompt_tokens=5,
        completion_tokens=3,
    )
    assert observed.prompt_tokens == 5
    with pytest.raises(ApplicationError, match="MODEL_USAGE_CONFLICT"):
        await RecordModelUsage(uow)(
            run_id=run_id,
            reservation_id=reservation.reservation_id,
            provider_operation_id="provider-op-1",
            prompt_tokens=6,
            completion_tokens=3,
        )


@pytest.mark.asyncio
async def test_reservation_budget_terminal_and_cross_project_identity(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, _, _, uow = await _seed_run(test_postgres_dsn, key=f"key-{uuid4().hex}")
    await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.INITIAL)
    await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.SCHEMA_REPAIR)
    with pytest.raises(ApplicationError, match="MODEL_REQUEST_BUDGET_EXHAUSTED"):
        await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.STRATEGY_REPAIR)
    await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.TRANSPORT_RETRY)
    with pytest.raises(ApplicationError, match="MODEL_REQUEST_BUDGET_EXHAUSTED"):
        await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.TRANSPORT_RETRY)
    with pytest.raises(ApplicationError, match="AI_RUN_ACTION_STATE_CONFLICT"):
        await RequestAIRunAction(uow)(
            run_id=run_id, action="resume", expected_version=0, idempotency_key="action-key"
        )


@pytest.mark.asyncio
async def test_project_scoped_and_concurrent_create_replay_and_action_replay(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    first = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name=f"P {uuid4().hex}", actor_id="s2", idempotency_key=f"p-{uuid4().hex}"
        )
    )
    second = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name=f"P {uuid4().hex}", actor_id="s2", idempotency_key=f"p-{uuid4().hex}"
        )
    )
    uow = PostgresAIRunUnitOfWork(sessions)
    request = CreateAIRunRequest(
        project_id=first.project_id,
        branch_id=first.active_branch_id,
        base_revision_id=first.root_revision_id,
        thread_id=f"thread-{uuid4().hex}",
        brief=_brief(),
        idempotency_key="project-scoped-key",
    )
    created, replayed = await asyncio.gather(CreateAIRun(uow)(request), CreateAIRun(uow)(request))
    assert created.run_id == replayed.run_id
    second_run = await CreateAIRun(uow)(
        CreateAIRunRequest(
            project_id=second.project_id,
            branch_id=second.active_branch_id,
            base_revision_id=second.root_revision_id,
            thread_id=f"thread-{uuid4().hex}",
            brief=_brief(),
            idempotency_key="project-scoped-key",
        )
    )
    assert second_run.run_id != created.run_id
    with pytest.raises(ApplicationError, match="AI_RUN_IDENTITY_INVALID"):
        await CreateAIRun(uow)(
            CreateAIRunRequest(
                project_id=second.project_id,
                branch_id=first.active_branch_id,
                base_revision_id=first.root_revision_id,
                thread_id=f"thread-{uuid4().hex}",
                brief=_brief(),
                idempotency_key=f"invalid-{uuid4().hex}",
            )
        )
    async with uow() as transaction:
        invalid_count = await transaction._session.scalar(  # type: ignore[attr-defined]
            select(func.count())
            .select_from(AIRunRow)
            .where(
                AIRunRow.project_id == second.project_id,
                AIRunRow.idempotency_key.like("invalid-%"),
            )
        )
    assert invalid_count == 0
    cancelled = await RequestAIRunAction(uow)(
        run_id=created.run_id, action="cancel", expected_version=0, idempotency_key="cancel-replay"
    )
    assert cancelled.status is AIRunStatus.CANCELLED
    replay_cancelled = await RequestAIRunAction(uow)(
        run_id=created.run_id, action="cancel", expected_version=0, idempotency_key="cancel-replay"
    )
    assert replay_cancelled.version == cancelled.version
    with pytest.raises(ApplicationError, match="MODEL_REQUEST_BUDGET_EXHAUSTED"):
        await ReserveModelRequest(uow)(run_id=created.run_id, kind=ModelRequestKind.INITIAL)
    await engine.dispose()


@pytest.mark.asyncio
async def test_populated_0013_downgrades_to_0012(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO observability.traces (id, run_id, thread_id, trace_name, status, started_at, updated_at) VALUES (gen_random_uuid(), 's2-downgrade', 'thread', 'test', 'succeeded', now(), now()) ON CONFLICT DO NOTHING"
                )
            )
            await connection.execute(
                text(
                    "UPDATE observability.usage_ledger SET estimated_cost_microusd = NULL WHERE estimated_cost_microusd = 0"
                )
            )
        await asyncio.to_thread(_downgrade, test_postgres_dsn)
        async with engine.connect() as connection:
            nullable = await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns WHERE table_schema='observability' AND table_name='usage_ledger' AND column_name='estimated_cost_microusd'"
                )
            )
        assert nullable == "NO"
    finally:
        await engine.dispose()


async def _run(uow: PostgresAIRunUnitOfWork, run_id: UUID):
    async with uow() as transaction:
        return await transaction.read_ai_run(run_id)
