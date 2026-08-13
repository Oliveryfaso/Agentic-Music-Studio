"""Real PostgreSQL coverage for the S2 durable AI-run ledger."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from motif_forge.agent.planner import (
    PersistentProviderBudgetLedger,
    PlannerUsage,
    ProviderBudgetExceeded,
)
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
    MarkAIRunPlanPending,
    PersistCompositionPlan,
    RecordAIRunApproval,
    RecordAIRunEvent,
    RecordModelUsage,
    RequestAIRunAction,
    ReserveModelRequest,
)
from motif_forge.application.errors import ApplicationError
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V1,
    PLAN_HASH_VERSION_V2,
    AIRun,
    AIRunEvent,
    AIRunStatus,
    ModelRequestKind,
    ModelUsageStatus,
    PersistedCompositionPlan,
    composition_plan_content_hash,
)
from motif_forge.domain.commands import AddTrackCommand, AddTrackPayload
from motif_forge.domain.ir import Track, TrackRole, TrackType
from motif_forge.domain.revisions import AuthorKind
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.tables import (
    AIRunActionIdempotencyRow,
    AIRunApprovalRow,
    AIRunEventRow,
    AIRunRow,
    BranchRow,
    ModelRequestReservationRow,
    OutboxEventRow,
)
from motif_forge.providers.deepseek import DeepSeekJsonClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine


def _upgrade(dsn: str, revision: str = "head") -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), revision)


def _downgrade(dsn: str, revision: str = "-1") -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.downgrade(Config(root / "alembic.ini"), revision)


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


@pytest.mark.asyncio
async def test_0015_preserves_legacy_plan_and_pending_approval_hash_references(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_downgrade, test_postgres_dsn, "20260813_0014")
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"legacy-plan-hash-{uuid4().hex}"
    )
    try:
        async with uow() as transaction:
            start_payload = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(OutboxEventRow.payload).where(
                    OutboxEventRow.aggregate_id == run_id,
                    OutboxEventRow.topic == "graph.start.requested",
                )
            )
        assert start_payload == {
            "schema_version": "graph-action.v1",
            "action": "start",
            "run_id": str(run_id),
            "thread_id": (await _run(uow, run_id)).thread_id,
            "run_type": "parent.generate.v1",
            "decision": None,
        }
        plan = _plan().model_copy(
            update={
                "sections": (
                    _plan().sections[0].model_copy(update={"energy": 0.2500001}),
                    _plan().sections[1],
                )
            }
        )
        legacy_hash = composition_plan_content_hash(
            plan, hash_version=PLAN_HASH_VERSION_V1
        )
        plan_id, approval_id = uuid4(), uuid4()
        interrupt_ref = f"server-ref-{uuid4().hex}"
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO app.composition_plans "
                    "(id, run_id, plan, content_hash, provider, model, prompt_version, "
                    "schema_version, style_pack_version, created_at) "
                    "VALUES (:id, :run_id, CAST(:plan AS jsonb), :hash, 'fallback', "
                    "'deterministic', 'p1', 'composition-plan.v1', 's1', now())"
                ),
                {
                    "id": plan_id,
                    "run_id": run_id,
                    "plan": plan.model_dump_json(),
                    "hash": legacy_hash,
                },
            )
            await connection.execute(
                text(
                    "UPDATE app.ai_runs SET status='waiting_approval', "
                    "pending_plan_id=:plan_id, pending_plan_content_hash=:hash, "
                    "pending_interrupt_ref=:interrupt WHERE id=:run_id"
                ),
                {
                    "plan_id": plan_id,
                    "hash": legacy_hash,
                    "interrupt": interrupt_ref,
                    "run_id": run_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO app.ai_run_approvals "
                    "(id, run_id, assertion_hash, decision, actor_id, "
                    "expected_plan_content_hash, interrupt_ref, decided_at) "
                    "VALUES (:id, :run_id, :assertion_hash, 'approve', 'legacy-test', "
                    ":hash, :interrupt, now())"
                ),
                {
                    "id": approval_id,
                    "run_id": run_id,
                    "assertion_hash": "a" * 64,
                    "hash": legacy_hash,
                    "interrupt": interrupt_ref,
                },
            )

        await asyncio.to_thread(_upgrade, test_postgres_dsn, "20260813_0015")
        async with engine.connect() as connection:
            debug_row = (
                await connection.execute(
                    text(
                        "SELECT plan, content_hash, hash_version FROM app.composition_plans "
                        "WHERE id=:id"
                    ),
                    {"id": plan_id},
                )
            ).one()
        debug_plan = CompositionPlan.model_validate(debug_row.plan, strict=False)
        assert debug_row.hash_version == PLAN_HASH_VERSION_V1
        assert debug_row.content_hash == composition_plan_content_hash(
            debug_plan, hash_version=PLAN_HASH_VERSION_V1
        ), (debug_row.content_hash, debug_row.hash_version, debug_plan.model_dump(mode="json"))

        await asyncio.to_thread(_downgrade, test_postgres_dsn, "20260813_0014")
        async with engine.connect() as connection:
            downgraded = (
                await connection.execute(
                    text(
                        "SELECT p.plan, p.content_hash, r.pending_plan_content_hash, "
                        "a.expected_plan_content_hash FROM app.composition_plans p "
                        "JOIN app.ai_runs r ON r.id=p.run_id "
                        "JOIN app.ai_run_approvals a ON a.run_id=r.id WHERE p.id=:id"
                    ),
                    {"id": plan_id},
                )
            ).one()
            hash_version_column = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema='app' AND table_name='composition_plans' "
                    "AND column_name='hash_version'"
                )
            )
        downgraded_plan = CompositionPlan.model_validate(downgraded.plan, strict=False)
        assert hash_version_column == 0
        assert downgraded.content_hash == composition_plan_content_hash(
            downgraded_plan, hash_version=PLAN_HASH_VERSION_V1
        )
        assert downgraded.pending_plan_content_hash == legacy_hash
        assert downgraded.expected_plan_content_hash == legacy_hash

        await asyncio.to_thread(_upgrade, test_postgres_dsn, "20260813_0015")

        async with uow() as transaction:
            loaded = await transaction.read_composition_plan(plan_id=plan_id, run_id=run_id)
        async with engine.connect() as connection:
            references = (
                await connection.execute(
                    text(
                        "SELECT p.hash_version, p.content_hash, r.pending_plan_content_hash, "
                        "a.expected_plan_content_hash FROM app.composition_plans p "
                        "JOIN app.ai_runs r ON r.id=p.run_id "
                        "JOIN app.ai_run_approvals a ON a.run_id=r.id WHERE p.id=:id"
                    ),
                    {"id": plan_id},
                )
            ).one()
        assert loaded.hash_version == PLAN_HASH_VERSION_V1
        assert loaded.content_hash == legacy_hash
        assert references == (PLAN_HASH_VERSION_V1, legacy_hash, legacy_hash, legacy_hash)
    finally:
        await _delete_seeded_project(engine, project_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_lossless_v2_plan_round_trips_after_0015(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"lossless-plan-hash-{uuid4().hex}"
    )
    try:
        plan = _plan().model_copy(
            update={
                "sections": (
                    _plan().sections[0].model_copy(update={"energy": 0.2500001}),
                    _plan().sections[1],
                )
            }
        )
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

        written = await PersistCompositionPlan(uow)(stored)
        async with uow() as transaction:
            loaded = await transaction.read_composition_plan(
                plan_id=stored.plan_id, run_id=run_id
            )

        assert written.hash_version == PLAN_HASH_VERSION_V2
        assert loaded == written
        assert loaded.plan.sections[0].energy == 0.2500001
    finally:
        await _delete_seeded_project(engine, project_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_0015_downgrade_refuses_v2_without_mutating_schema_or_references(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"guarded-v2-downgrade-{uuid4().hex}"
    )
    try:
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
        written = await PersistCompositionPlan(uow)(stored)
        approval_id = uuid4()
        interrupt_ref = f"guard-ref-{uuid4().hex}"
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE app.ai_runs SET status='waiting_approval', "
                    "pending_plan_id=:plan_id, pending_plan_content_hash=:hash, "
                    "pending_interrupt_ref=:interrupt WHERE id=:run_id"
                ),
                {
                    "plan_id": written.plan_id,
                    "hash": written.content_hash,
                    "interrupt": interrupt_ref,
                    "run_id": run_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO app.ai_run_approvals "
                    "(id, run_id, assertion_hash, decision, actor_id, "
                    "expected_plan_content_hash, interrupt_ref, decided_at) "
                    "VALUES (:id, :run_id, :assertion_hash, 'approve', 'guard-test', "
                    ":hash, :interrupt, now())"
                ),
                {
                    "id": approval_id,
                    "run_id": run_id,
                    "assertion_hash": "b" * 64,
                    "hash": written.content_hash,
                    "interrupt": interrupt_ref,
                },
            )

        async def snapshot() -> tuple[object, ...]:
            async with engine.connect() as connection:
                head = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                column = (
                    await connection.execute(
                        text(
                            "SELECT data_type, is_nullable, column_default "
                            "FROM information_schema.columns WHERE table_schema='app' "
                            "AND table_name='composition_plans' AND column_name='hash_version'"
                        )
                    )
                ).one()
                constraint = await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname='app' "
                        "AND t.relname='composition_plans' "
                        "AND c.conname LIKE '%composition_plans_hash_version_valid'"
                    )
                )
                row = (
                    await connection.execute(
                        text(
                            "SELECT p.plan, p.content_hash, p.hash_version, "
                            "r.pending_plan_content_hash, a.expected_plan_content_hash "
                            "FROM app.composition_plans p "
                            "JOIN app.ai_runs r ON r.id=p.run_id "
                            "JOIN app.ai_run_approvals a ON a.run_id=r.id WHERE p.id=:id"
                        ),
                        {"id": written.plan_id},
                    )
                ).one()
            return (head, tuple(column), constraint, tuple(row))

        before = await snapshot()
        with pytest.raises(
            RuntimeError,
            match=r"cannot downgrade 20260813_0015.*lossless-v2",
        ):
            await asyncio.to_thread(_downgrade, test_postgres_dsn, "20260813_0014")
        after = await snapshot()

        assert before == after
        assert after[0] == "20260813_0016"
        assert after[2] == 1
        assert after[3][2:] == (
            PLAN_HASH_VERSION_V2,
            written.content_hash,
            written.content_hash,
        )
    finally:
        await _delete_seeded_project(engine, project_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_digest_v1_v2_replay_is_a_provenance_conflict(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"same-digest-version-replay-{uuid4().hex}"
    )
    try:
        plan = _plan()
        v1_hash = composition_plan_content_hash(plan, hash_version=PLAN_HASH_VERSION_V1)
        v2_hash = composition_plan_content_hash(plan, hash_version=PLAN_HASH_VERSION_V2)
        assert v1_hash == v2_hash
        plan_id = uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO app.composition_plans "
                    "(id, run_id, plan, content_hash, hash_version, provider, model, "
                    "prompt_version, schema_version, style_pack_version, created_at) "
                    "VALUES (:id, :run_id, CAST(:plan AS jsonb), :hash, :hash_version, "
                    "'fallback', 'deterministic', 'p1', 'composition-plan.v1', 's1', now())"
                ),
                {
                    "id": plan_id,
                    "run_id": run_id,
                    "plan": plan.model_dump_json(),
                    "hash": v1_hash,
                    "hash_version": PLAN_HASH_VERSION_V1,
                },
            )
        replay = PersistedCompositionPlan(
            plan_id=uuid4(),
            run_id=run_id,
            plan=plan,
            content_hash=v2_hash,
            hash_version=PLAN_HASH_VERSION_V2,
            provider="fallback",
            model="deterministic",
            prompt_version="p1",
            schema_version="composition-plan.v1",
            style_pack_version="s1",
        )

        with pytest.raises(ApplicationError) as raised:
            await PersistCompositionPlan(uow)(replay)

        assert raised.value.code == "PLAN_PROVENANCE_CONFLICT"
        async with uow() as transaction:
            loaded = await transaction.read_composition_plan(plan_id=plan_id, run_id=run_id)
        assert loaded.hash_version == PLAN_HASH_VERSION_V1
        assert loaded.plan_id == plan_id
        v1_replay = replay.model_copy(
            update={
                "plan_id": uuid4(),
                "hash_version": PLAN_HASH_VERSION_V1,
            }
        )
        replayed = await PersistCompositionPlan(uow)(v1_replay)
        assert replayed == loaded
    finally:
        await _delete_seeded_project(engine, project_id)
        await engine.dispose()


async def _seed_run(
    dsn: str, *, key: str = "s2-ai-run-key", max_model_requests: int = 3
) -> tuple[UUID, UUID, UUID, PostgresAIRunUnitOfWork, AsyncEngine]:
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
            max_model_requests=max_model_requests,
        )
    )
    return run.run_id, project.project_id, project.root_revision_id, run_uow, engine


async def _delete_seeded_project(engine: AsyncEngine, project_id: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        await connection.execute(
            text("DELETE FROM app.projects WHERE id=:project_id"),
            {"project_id": project_id},
        )


@pytest.mark.asyncio
async def test_create_replay_plan_events_approval_actions_and_ledger(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    replay_key = f"s2-ai-run-{uuid4().hex}"
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=replay_key
    )
    try:
        replay = await CreateAIRun(uow)(
            CreateAIRunRequest(
                project_id=project_id,
                branch_id=(await _run(uow, run_id)).branch_id,
                base_revision_id=(await _run(uow, run_id)).base_revision_id,
                thread_id=(await _run(uow, run_id)).thread_id,
                brief=_brief(),
                    idempotency_key=replay_key,
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
        alternate_plan = _plan().model_copy(update={"bpm": 81})
        alternate = stored.model_copy(
            update={
                "plan_id": uuid4(),
                "plan": alternate_plan,
                "content_hash": composition_plan_content_hash(alternate_plan),
            }
        )
        await PersistCompositionPlan(uow)(alternate)
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
        next_event = await RecordAIRunEvent(uow)(
            event.model_copy(
                update={
                    "event_id": uuid4(),
                    "event_type": "plan.persisted",
                    "dedupe_key": "plan",
                }
            )
        )
        assert next_event.sequence > event.sequence
        events = await ListAIRunEvents(uow)(run_id)
        assert [item.sequence for item in events] == sorted(item.sequence for item in events)
        assert [item.sequence for item in events][-2:] == [event.sequence, next_event.sequence]
        assert await ListAIRunEvents(uow)(run_id, after_sequence=event.sequence) == (next_event,)
        pending = await MarkAIRunPlanPending(uow)(
            run_id=run_id, plan_id=stored.plan_id, expected_version=0
        )
        with pytest.raises(ApplicationError, match="AI_RUN_ACTION_INVALID"):
            await RequestAIRunAction(uow)(
                run_id=run_id,
                action="resume",
                expected_version=pending.version,
                idempotency_key="no-bypass",
            )
        with pytest.raises(ApplicationError, match="AI_RUN_APPROVAL_INVALID"):
            await RecordAIRunApproval(uow)(
                run_id=run_id,
                actor_id="human",
                decision="approve",
                assertion="too short",
                expected_version=pending.version,
                expected_plan_content_hash=stored.content_hash,
                interrupt_ref=pending.pending_interrupt_ref,
            )
        with pytest.raises(ApplicationError, match="AI_RUN_APPROVAL_CONFLICT"):
            await RecordAIRunApproval(uow)(
                run_id=run_id,
                actor_id="human",
                decision="approve",
                assertion="I approve this composition after a full review.",
                expected_version=pending.version,
                expected_plan_content_hash=alternate.content_hash,
                interrupt_ref=pending.pending_interrupt_ref,
            )
        with pytest.raises(ApplicationError, match="AI_RUN_APPROVAL_CONFLICT"):
            await RecordAIRunApproval(uow)(
                run_id=run_id,
                actor_id="human",
                decision="approve",
                assertion="I approve this composition after a full review.",
                expected_version=pending.version,
                expected_plan_content_hash=stored.content_hash,
                interrupt_ref="forged-interrupt-reference-value",
            )
        approval = await RecordAIRunApproval(uow)(
            run_id=run_id,
            actor_id="human",
            decision="approve",
            assertion="I approve this composition after a full review.",
            expected_version=pending.version,
            expected_plan_content_hash=stored.content_hash,
            interrupt_ref=pending.pending_interrupt_ref,
        )
        assert approval.assertion_hash != "I approve this composition after a full review."
        async with uow() as transaction:
            stored_hash = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(AIRunApprovalRow.assertion_hash).where(AIRunApprovalRow.run_id == run_id)
            )
        assert stored_hash == approval.assertion_hash
        approved = await _run(uow, run_id)
        assert approved.status is AIRunStatus.MATERIALIZING
        assert approved.approval_assertion_hash == approval.assertion_hash
        assert approved.pending_plan_id is None
        assert approved.pending_plan_content_hash is None
        assert approved.pending_interrupt_ref is None
        async with uow() as transaction:
            approval_count = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(func.count()).select_from(AIRunApprovalRow).where(AIRunApprovalRow.run_id == run_id)
            )
            resume_count = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(func.count()).select_from(OutboxEventRow).where(
                    OutboxEventRow.aggregate_id == run_id,
                    OutboxEventRow.topic == "graph.resume.requested",
                )
            )
            resume_payload = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(OutboxEventRow.payload).where(
                    OutboxEventRow.aggregate_id == run_id,
                    OutboxEventRow.topic == "graph.resume.requested",
                )
            )
        assert approval_count == resume_count == 1
        assert resume_payload == {
            "schema_version": "graph-action.v1",
            "action": "resume",
            "run_id": str(run_id),
            "thread_id": approved.thread_id,
            "run_type": "parent.generate.v1",
            "decision": {
                "decision": "approve",
                "actor_id": "human",
                "approval_assertion": "I approve this composition after a full review.",
                "expected_plan_hash": stored.content_hash,
                "note": "",
            },
        }
        approved_replay = await RecordAIRunApproval(uow)(
            run_id=run_id,
            actor_id="human",
            decision="approve",
            assertion="I approve this composition after a full review.",
            expected_version=pending.version,
            expected_plan_content_hash=stored.content_hash,
            interrupt_ref=pending.pending_interrupt_ref,
        )
        assert approved_replay.approval_id == approval.approval_id
        reservation = await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.INITIAL)
        provider_operation_id = f"provider-op-{run_id}"
        observed = await RecordModelUsage(uow)(
            run_id=run_id,
            reservation_id=reservation.reservation_id,
            provider_operation_id=provider_operation_id,
            usage_status=ModelUsageStatus.PARTIAL,
            prompt_tokens=5,
            completion_tokens=3,
            total_tokens=8,
            prompt_cache_hit_tokens=None,
            prompt_cache_miss_tokens=None,
            reasoning_tokens=None,
        )
        assert observed.prompt_tokens == 5
        with pytest.raises(ApplicationError, match="MODEL_USAGE_CONFLICT"):
            await RecordModelUsage(uow)(
                run_id=run_id,
                reservation_id=reservation.reservation_id,
                provider_operation_id=provider_operation_id,
                usage_status=ModelUsageStatus.PARTIAL,
                prompt_tokens=6,
                completion_tokens=3,
                total_tokens=9,
                prompt_cache_hit_tokens=None,
                prompt_cache_miss_tokens=None,
                reasoning_tokens=None,
            )
        rejected = await CreateAIRun(uow)(
            CreateAIRunRequest(
                project_id=project_id,
                branch_id=approved.branch_id,
                base_revision_id=approved.base_revision_id,
                thread_id=f"reject-{uuid4().hex}",
                brief=_brief(),
                idempotency_key=f"reject-{uuid4().hex}",
            )
        )
        rejected_plan = stored.model_copy(update={"plan_id": uuid4(), "run_id": rejected.run_id})
        await PersistCompositionPlan(uow)(rejected_plan)
        rejected_pending = await MarkAIRunPlanPending(uow)(
            run_id=rejected.run_id, plan_id=rejected_plan.plan_id, expected_version=0
        )
        rejection = await RecordAIRunApproval(uow)(
            run_id=rejected.run_id,
            actor_id="human",
            decision="reject",
            assertion="I reject this composition after a full review.",
            expected_version=rejected_pending.version,
            expected_plan_content_hash=rejected_plan.content_hash,
            interrupt_ref=rejected_pending.pending_interrupt_ref,
        )
        rejection_replay = await RecordAIRunApproval(uow)(
            run_id=rejected.run_id,
            actor_id="human",
            decision="reject",
            assertion="I reject this composition after a full review.",
            expected_version=rejected_pending.version,
            expected_plan_content_hash=rejected_plan.content_hash,
            interrupt_ref=rejected_pending.pending_interrupt_ref,
        )
        assert rejection_replay.approval_id == rejection.approval_id
        assert (await _run(uow, rejected.run_id)).status is AIRunStatus.REJECTED
        async with uow() as transaction:
            rejected_resume = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(func.count()).select_from(OutboxEventRow).where(
                    OutboxEventRow.aggregate_id == rejected.run_id,
                    OutboxEventRow.topic == "graph.resume.requested",
                )
            )
        assert rejected_resume == 0
    finally:
        await _delete_seeded_project(engine, project_id)
        await engine.dispose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_provider_budget_adapter_survives_reconstruction_and_uses_run_ledger(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"provider-budget-{uuid4().hex}"
    )
    try:
        first_process = PersistentProviderBudgetLedger(uow, run_id=run_id)
        initial = await first_process.reserve_request(
            run_id=run_id, kind=ModelRequestKind.INITIAL
        )
        first_snapshot = await first_process.record_usage(
            reservation_id=initial.reservation_id,
            usage=PlannerUsage(prompt_tokens=120, completion_tokens=30, total_tokens=150),
        )
        assert first_snapshot.submitted_requests == 1
        assert first_snapshot.total_tokens == 150

        reconstructed = PersistentProviderBudgetLedger(uow, run_id=run_id)
        retry = await reconstructed.reserve_request(
            run_id=run_id, kind=ModelRequestKind.TRANSPORT_RETRY
        )
        second_snapshot = await reconstructed.record_usage(
            reservation_id=retry.reservation_id,
            usage=PlannerUsage(prompt_tokens=80, completion_tokens=20, total_tokens=100),
        )

        assert second_snapshot.submitted_requests == 2
        assert second_snapshot.total_tokens == 250
        persisted = await _run(uow, run_id)
        assert persisted.submitted_model_requests == 2
        assert persisted.prompt_tokens == 200
        assert persisted.completion_tokens == 50
        assert persisted.total_tokens == 250
    finally:
        async with engine.begin() as connection:  # type: ignore[union-attr]
            await connection.execute(
                text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
                {"project_id": project_id},
            )
            await connection.execute(
                text("DELETE FROM app.projects WHERE id=:project_id"),
                {"project_id": project_id},
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM app.ai_runs WHERE id=:run_id"),
                    {"run_id": run_id},
                )
            ) == 0
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM app.projects WHERE id=:project_id"),
                    {"project_id": project_id},
                )
            ) == 0
        await engine.dispose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_locked_one_request_run_blocks_transport_retry_before_second_post(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn,
        key=f"provider-one-request-{uuid4().hex}",
        max_model_requests=1,
    )
    posts = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(503)

    async def no_sleep(delay: float) -> None:
        del delay

    try:
        ledger = PersistentProviderBudgetLedger(uow, run_id=run_id, max_requests=1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as http_client:
            client = DeepSeekJsonClient(
                api_key="test-key",
                http_client=http_client,
                max_attempts=2,
                run_id=run_id,
                budget_ledger=ledger,
                    sleep=no_sleep,
            )
            with pytest.raises(ProviderBudgetExceeded, match="request budget"):
                await client.complete_json(
                    messages=[], output_model=CompositionPlan, thinking="enabled", max_tokens=512
                )
        assert posts == 1
        reconstructed = PersistentProviderBudgetLedger(
            uow, run_id=run_id, max_requests=1
        )
        with pytest.raises(ProviderBudgetExceeded, match="request budget"):
            await reconstructed.reserve_request(
                run_id=run_id, kind=ModelRequestKind.TRANSPORT_RETRY
            )
        async with uow() as transaction:
            reservations = (
                await transaction._session.execute(  # type: ignore[attr-defined]
                    select(ModelRequestReservationRow).where(
                        ModelRequestReservationRow.run_id == run_id
                    )
                )
            ).scalars().all()
        assert len(reservations) == 1
        assert reservations[0].request_kind == "initial"
        assert posts == 1
    finally:
        async with engine.begin() as connection:  # type: ignore[union-attr]
            await connection.execute(
                text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
                {"project_id": project_id},
            )
            await connection.execute(
                text("DELETE FROM app.projects WHERE id=:project_id"),
                {"project_id": project_id},
            )
        await engine.dispose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_real_pg_ledger_preserves_provider_total_and_missing_usage_fail_closed(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"provider-truth-{uuid4().hex}"
    )
    posts = 0

    def divergent_handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(
            200,
            json={
                "id": "divergent-total",
                "choices": [{"finish_reason": "stop", "message": {"content": _plan().model_dump_json()}}],
                "usage": {"prompt_tokens": 9_000, "completion_tokens": 2_000, "total_tokens": 12_001},
            },
        )

    try:
        ledger = PersistentProviderBudgetLedger(uow, run_id=run_id)
        async with httpx.AsyncClient(transport=httpx.MockTransport(divergent_handler)) as http_client:
            client = DeepSeekJsonClient(
                api_key="test-key", http_client=http_client, max_attempts=1,
                run_id=run_id, budget_ledger=ledger,
            )
            with pytest.raises(ProviderBudgetExceeded, match="token budget"):
                await client.complete_json(
                    messages=[], output_model=CompositionPlan, thinking="enabled", max_tokens=512
                )
        reconstructed = PersistentProviderBudgetLedger(uow, run_id=run_id)
        before = posts
        with pytest.raises(ProviderBudgetExceeded):
            await reconstructed.reserve_request(run_id=run_id, kind=ModelRequestKind.TRANSPORT_RETRY)
        assert posts == before == 1
        persisted = await _run(uow, run_id)
        assert (persisted.prompt_tokens, persisted.completion_tokens, persisted.total_tokens) == (9_000, 2_000, 12_001)
        assert persisted.model_usage_status is ModelUsageStatus.PARTIAL

        missing_run_id, missing_project_id, _, missing_uow, missing_engine = await _seed_run(
            test_postgres_dsn, key=f"provider-missing-{uuid4().hex}"
        )
        missing_posts = 0

        def missing_handler(request: httpx.Request) -> httpx.Response:
            nonlocal missing_posts
            missing_posts += 1
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]})

        missing_ledger = PersistentProviderBudgetLedger(missing_uow, run_id=missing_run_id)
        async with httpx.AsyncClient(transport=httpx.MockTransport(missing_handler)) as http_client:
            client = DeepSeekJsonClient(api_key="test-key", http_client=http_client, max_attempts=1, run_id=missing_run_id, budget_ledger=missing_ledger)
            with pytest.raises(ProviderBudgetExceeded, match="usage facts"):
                await client.complete_json(messages=[], output_model=CompositionPlan, thinking="enabled", max_tokens=512, schema_repair_attempts=1)
        assert missing_posts == 1
        missing_persisted = await _run(missing_uow, missing_run_id)
        assert missing_persisted.model_usage_status is ModelUsageStatus.UNKNOWN
        assert missing_persisted.total_tokens is None
        async with missing_uow() as transaction:
            reservations = (await transaction._session.execute(select(ModelRequestReservationRow).where(ModelRequestReservationRow.run_id == missing_run_id))).scalars().all()  # type: ignore[attr-defined]
        assert len(reservations) == 1
        assert reservations[0].usage_status == "unknown"
        reconstructed_missing = PersistentProviderBudgetLedger(
            missing_uow, run_id=missing_run_id
        )
        with pytest.raises(ProviderBudgetExceeded, match="usage facts"):
            await reconstructed_missing.reserve_request(
                run_id=missing_run_id, kind=ModelRequestKind.TRANSPORT_RETRY
            )
        assert missing_posts == 1
    finally:
        async with engine.begin() as connection:  # type: ignore[union-attr]
            await connection.execute(
                text(
                    "DELETE FROM app.audit_events "
                    "WHERE project_id IN (:project_id, :missing_project_id)"
                ),
                {
                    "project_id": project_id,
                    "missing_project_id": locals().get("missing_project_id", project_id),
                },
            )
            await connection.execute(text("DELETE FROM app.projects WHERE id IN (:project_id, :missing_project_id)"), {"project_id": project_id, "missing_project_id": locals().get("missing_project_id", project_id)})
        await engine.dispose()  # type: ignore[union-attr]
        if "missing_engine" in locals():
            await missing_engine.dispose()


@pytest.mark.asyncio
async def test_reservation_budget_terminal_and_cross_project_identity(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, _, _, uow, engine = await _seed_run(test_postgres_dsn, key=f"key-{uuid4().hex}")
    try:
        await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.INITIAL)
        await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.SCHEMA_REPAIR)
        with pytest.raises(ApplicationError, match="MODEL_REQUEST_BUDGET_EXHAUSTED"):
            await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.STRATEGY_REPAIR)
        await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.TRANSPORT_RETRY)
        with pytest.raises(ApplicationError, match="MODEL_REQUEST_BUDGET_EXHAUSTED"):
            await ReserveModelRequest(uow)(run_id=run_id, kind=ModelRequestKind.TRANSPORT_RETRY)
        with pytest.raises(ApplicationError, match="AI_RUN_ACTION_INVALID"):
            await RequestAIRunAction(uow)(
                run_id=run_id, action="resume", expected_version=0, idempotency_key="action-key"
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_project_scoped_and_concurrent_create_replay_and_action_replay(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    try:
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
        child = await RequestAIRunAction(uow)(
        run_id=created.run_id, action="retry", expected_version=cancelled.version, idempotency_key="retry-child"
        )
        child_replay = await RequestAIRunAction(uow)(
        run_id=created.run_id, action="retry", expected_version=cancelled.version, idempotency_key="retry-child"
        )
        assert child_replay.run_id == child.run_id
        assert child.parent_run_id == created.run_id
        assert child.thread_id != created.thread_id
        assert child.submitted_model_requests == child.prompt_tokens == child.completion_tokens == 0
        assert (await _run(uow, created.run_id)) == cancelled
        async with uow() as transaction:
            retry_outbox_count = await transaction._session.scalar(  # type: ignore[attr-defined]
            select(func.count()).select_from(OutboxEventRow).where(
                OutboxEventRow.aggregate_id == child.run_id,
                    OutboxEventRow.topic == "graph.start.requested",
                )
            )
            child_created_count = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(func.count()).select_from(AIRunEventRow).where(
                    AIRunEventRow.run_id == child.run_id,
                    AIRunEventRow.event_type == "ai_run.created",
                )
            )
            cancel_payload = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(OutboxEventRow.payload).where(
                    OutboxEventRow.aggregate_id == created.run_id,
                    OutboxEventRow.topic == "graph.cancel.requested",
                )
            )
            retry_payload = await transaction._session.scalar(  # type: ignore[attr-defined]
                select(OutboxEventRow.payload).where(
                    OutboxEventRow.aggregate_id == child.run_id,
                )
            )
        assert retry_outbox_count == child_created_count == 1
        assert cancel_payload == {
            "schema_version": "graph-action.v1",
            "action": "cancel",
            "run_id": str(created.run_id),
            "thread_id": created.thread_id,
            "run_type": "parent.generate.v1",
            "decision": None,
        }
        assert retry_payload == {
            "schema_version": "graph-action.v1",
            "action": "start",
            "run_id": str(child.run_id),
            "thread_id": child.thread_id,
            "run_type": "parent.generate.v1",
            "decision": None,
        }
        with pytest.raises(ApplicationError, match="IDEMPOTENCY_KEY_REUSED"):
            await RequestAIRunAction(uow)(
                run_id=created.run_id,
                action="retry",
                expected_version=cancelled.version + 1,
                idempotency_key="retry-child",
            )
        sibling = await CreateAIRun(uow)(
            CreateAIRunRequest(
                project_id=first.project_id,
                branch_id=first.active_branch_id,
                base_revision_id=first.root_revision_id,
                thread_id=f"sibling-{uuid4().hex}",
                brief=_brief(),
                idempotency_key=f"sibling-{uuid4().hex}",
            )
        )
        sibling_cancelled = await RequestAIRunAction(uow)(
            run_id=sibling.run_id,
            action="cancel",
            expected_version=0,
            idempotency_key="cancel-sibling",
        )
        sibling_child = await RequestAIRunAction(uow)(
            run_id=sibling.run_id,
            action="retry",
            expected_version=sibling_cancelled.version,
            idempotency_key="retry-child",
        )
        assert sibling_child.run_id != child.run_id
        with pytest.raises(ApplicationError, match="MODEL_REQUEST_BUDGET_EXHAUSTED"):
            await ReserveModelRequest(uow)(run_id=created.run_id, kind=ModelRequestKind.INITIAL)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_populated_0013_downgrades_to_0012(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    try:
        trace_id, span_id, operation_id = uuid4(), uuid4(), f"downgrade-{uuid4().hex}"
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO observability.traces (id, run_id, thread_id, trace_name, status, started_at, updated_at) VALUES (:id, :run_id, 'thread', 'test', 'succeeded', now(), now())"
                ),
                {"id": trace_id, "run_id": operation_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO observability.trace_spans (id, trace_id, operation_id, run_id, node, span_kind, status, safe_summary, started_at, ended_at, latency_ms) VALUES (:id, :trace_id, :operation_id, :run_id, 'test', 'model', 'succeeded', '{}'::jsonb, now(), now(), 0)"
                ),
                {"id": span_id, "trace_id": trace_id, "operation_id": operation_id, "run_id": operation_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO observability.usage_ledger (operation_id, trace_span_id, run_id, node, provider, model, model_calls, prompt_tokens, completion_tokens, total_tokens, prompt_cache_hit_tokens, prompt_cache_miss_tokens, reasoning_tokens, estimated_cost_microusd, created_at) VALUES (:operation_id, :span_id, :run_id, 'test', 'provider', 'model', 1, 1, 2, 3, 0, 0, 0, NULL, now())"
                ),
                {"operation_id": operation_id, "span_id": span_id, "run_id": operation_id},
            )
        await asyncio.to_thread(_downgrade, test_postgres_dsn, "20260812_0012")
        async with engine.connect() as connection:
            nullable = await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns WHERE table_schema='observability' AND table_name='usage_ledger' AND column_name='estimated_cost_microusd'"
                )
            )
            legacy_cost = await connection.scalar(
                text("SELECT estimated_cost_microusd FROM observability.usage_ledger WHERE operation_id=:operation_id"),
                {"operation_id": operation_id},
            )
            removed = await connection.scalar(text("SELECT to_regclass('app.ai_runs')"))
            removed_approval = await connection.scalar(text("SELECT to_regclass('app.ai_run_approvals')"))
            removed_plan = await connection.scalar(text("SELECT to_regclass('app.composition_plans')"))
            removed_event = await connection.scalar(text("SELECT to_regclass('app.ai_run_events')"))
            removed_reservation = await connection.scalar(
                text("SELECT to_regclass('app.ai_model_request_reservations')")
            )
            removed_action_ledger = await connection.scalar(
                text("SELECT to_regclass('app.ai_run_action_idempotency')")
            )
        assert nullable == "NO"
        assert legacy_cost == 0
        assert removed is None
        assert removed_approval is None
        assert removed_plan is None
        assert removed_event is None
        assert removed_reservation is None
        assert removed_action_ledger is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pending_plan_grouped_constraint_rejects_partial_tuples(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, _, _, _, engine = await _seed_run(test_postgres_dsn, key=f"pending-{uuid4().hex}")
    try:
        for status, plan_id, content_hash, interrupt_ref in (
            ("waiting_approval", None, "a" * 64, "server-ref-abcdefghijklmnopqrstuvwxyz"),
            ("waiting_approval", uuid4(), None, "server-ref-abcdefghijklmnopqrstuvwxyz"),
            ("waiting_approval", uuid4(), "a" * 64, None),
            ("queued", uuid4(), None, None),
            ("materializing", None, "a" * 64, None),
            ("queued", uuid4(), "a" * 64, None),
        ):
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text("UPDATE app.ai_runs SET status=:status, pending_plan_id=:plan_id, pending_plan_content_hash=:content_hash, pending_interrupt_ref=:interrupt_ref WHERE id=:id"),
                        {"status": status, "plan_id": plan_id, "content_hash": content_hash, "interrupt_ref": interrupt_ref, "id": run_id},
                    )
        async with engine.connect() as connection:
            state = await connection.execute(
                text("SELECT status, pending_plan_id, pending_plan_content_hash, pending_interrupt_ref FROM app.ai_runs WHERE id=:id"),
                {"id": run_id},
            )
        assert state.one() == ("queued", None, None, None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pending_plan_cancel_consumes_interrupt_and_replays_once(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, _, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"pending-cancel-{uuid4().hex}"
    )
    try:
        plan = _plan()
        stored = PersistedCompositionPlan(
            plan_id=uuid4(), run_id=run_id, plan=plan,
            content_hash=composition_plan_content_hash(plan), provider="fallback",
            model="deterministic", prompt_version="p1", schema_version="composition-plan.v1",
            style_pack_version="s1",
        )
        await PersistCompositionPlan(uow)(stored)
        pending = await MarkAIRunPlanPending(uow)(
            run_id=run_id, plan_id=stored.plan_id, expected_version=0
        )
        cancelled = await RequestAIRunAction(uow)(
            run_id=run_id,
            action="cancel",
            expected_version=pending.version,
            idempotency_key="cancel-pending",
        )
        assert cancelled.status is AIRunStatus.CANCELLED
        assert cancelled.version == pending.version + 1
        assert cancelled.terminal_at is not None
        assert (
            cancelled.pending_plan_id,
            cancelled.pending_plan_content_hash,
            cancelled.pending_interrupt_ref,
        ) == (None, None, None)
        replay = await RequestAIRunAction(uow)(
            run_id=run_id,
            action="cancel",
            expected_version=pending.version,
            idempotency_key="cancel-pending",
        )
        assert replay == cancelled
        async with engine.connect() as connection:
            outbox_count = await connection.scalar(
                select(func.count()).select_from(OutboxEventRow).where(
                    OutboxEventRow.aggregate_id == run_id,
                    OutboxEventRow.dedupe_key == f"ai-run:{run_id}:cancel:cancel-pending",
                )
            )
        assert outbox_count == 1
    finally:
        await _delete_seeded_project(engine, project_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_retry_outbox_failure_rolls_back_child_event_and_action_ledger(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, _, _, uow, engine = await _seed_run(test_postgres_dsn, key=f"retry-rollback-{uuid4().hex}")
    retry_key = "retry-outbox-conflict"
    try:
        parent = await RequestAIRunAction(uow)(
            run_id=run_id, action="cancel", expected_version=0, idempotency_key="cancel-for-retry"
        )
        now = datetime.now(UTC)
        child_id, thread_id, event_id, failed_outbox_id, preseeded_outbox_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        async with engine.begin() as connection:
            await connection.execute(
                insert(OutboxEventRow).values(
                    id=preseeded_outbox_id, aggregate_type="test", aggregate_id=uuid4(), topic="test",
                    dedupe_key=f"ai-run:{run_id}:retry:{retry_key}", payload={}, status="pending",
                    attempts=0, available_at=now, created_at=now,
                )
            )
        with pytest.raises(IntegrityError):
            retry_ids = iter((child_id, thread_id, event_id, failed_outbox_id))
            await RequestAIRunAction(uow, id_factory=lambda: next(retry_ids))(
                run_id=run_id,
                action="retry",
                expected_version=parent.version,
                idempotency_key=retry_key,
            )
        assert await _run(uow, run_id) == parent
        async with engine.connect() as connection:
            child_count = await connection.scalar(
                select(func.count()).select_from(AIRunRow).where(AIRunRow.parent_run_id == run_id)
            )
            ledger_count = await connection.scalar(
                select(func.count()).select_from(AIRunActionIdempotencyRow).where(
                    AIRunActionIdempotencyRow.parent_run_id == run_id,
                    AIRunActionIdempotencyRow.action == "retry",
                    AIRunActionIdempotencyRow.idempotency_key == retry_key,
                )
            )
            child_event_count = await connection.scalar(
                select(func.count()).select_from(AIRunEventRow).where(
                    AIRunEventRow.event_id == event_id
                )
            )
            retry_outboxes = (
                await connection.execute(
                    select(OutboxEventRow.id).where(
                        OutboxEventRow.dedupe_key == f"ai-run:{run_id}:retry:{retry_key}"
                    )
                )
            ).scalars().all()
        assert child_count == ledger_count == child_event_count == 0
        assert retry_outboxes == [preseeded_outbox_id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_atomic_create_failure_and_database_budget_constraints(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, root_id, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"constraints-{uuid4().hex}"
    )
    try:
        conflict_run_id, conflict_key = uuid4(), f"rollback-{uuid4().hex}"
        now = datetime.now(UTC)
        async with uow() as transaction:
            await transaction._session.execute(  # type: ignore[attr-defined]
                insert(OutboxEventRow).values(
                    id=uuid4(), aggregate_type="ai_run", aggregate_id=uuid4(),
                    topic="test", dedupe_key=f"ai-run:{conflict_run_id}:graph.start.requested",
                    payload={}, status="pending", attempts=0, available_at=now, created_at=now,
                )
            )
        failed_run = AIRun(
            run_id=conflict_run_id, project_id=project_id,
            branch_id=(await _run(uow, run_id)).branch_id, base_revision_id=root_id,
            thread_id=f"rollback-{uuid4().hex}", idempotency_key=conflict_key,
        )
        with pytest.raises(IntegrityError):
            async with uow() as transaction:
                await transaction.create_ai_run(
                    run=failed_run,
                    created_event=AIRunEvent(
                        sequence=1, event_id=uuid4(), run_id=conflict_run_id,
                        event_type="ai_run.created", phase="queued", payload={}, dedupe_key="created",
                    ),
                    outbox_event_id=uuid4(), request_hash="x" * 64,
                )
        async with engine.connect() as connection:
            assert await connection.scalar(select(func.count()).select_from(AIRunRow).where(AIRunRow.id == conflict_run_id)) == 0
            assert await connection.scalar(
                select(func.count()).select_from(AIRunEventRow).where(AIRunEventRow.run_id == conflict_run_id)
            ) == 0
            assert await connection.scalar(select(func.count()).select_from(OutboxEventRow).where(OutboxEventRow.aggregate_id == conflict_run_id)) == 0
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE app.ai_runs SET submitted_model_requests=4 WHERE id=:id"), {"id": run_id})
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE app.ai_runs SET prompt_tokens=-1 WHERE id=:id"), {"id": run_id})
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text("INSERT INTO app.ai_model_request_reservations (id, run_id, request_ordinal, request_kind, status, prompt_tokens, completion_tokens, created_at) VALUES (:id, :run_id, 99, 'initial', 'reserved', -1, 0, now())"), {"id": uuid4(), "run_id": run_id})
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_locked_branch_head_rejects_stale_and_other_branch_base(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, root_id, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"head-{uuid4().hex}"
    )
    try:
        initial = await _run(uow, run_id)
        commit = await CommitCommandBatch(PostgresUnitOfWork(create_session_factory(engine)))(
            CommitCommandBatchRequest(
                project_id=project_id, branch_id=initial.branch_id, base_revision_id=root_id,
                commands=(AddTrackCommand(
                    command_id=uuid4(), actor_kind="human", client_sequence=0,
                    payload=AddTrackPayload(track=Track(
                        track_id=uuid4(), track_type=TrackType.INSTRUMENT,
                        name="Head Test", role=TrackRole.HARMONY, instrument_ref="builtin:piano",
                    )),
                ),),
                actor_id="test", author_kind=AuthorKind.HUMAN, reason="HEAD_TEST",
                idempotency_key=f"commit-{uuid4().hex}",
            )
        )
        other_branch_id = uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                insert(BranchRow).values(
                    id=other_branch_id, project_id=project_id, name=f"other-{uuid4().hex}",
                    head_revision_id=root_id, base_revision_id=root_id,
                    created_at=datetime.now(UTC), updated_at=datetime.now(UTC), created_by="test",
                )
            )
        for branch_id, revision_id, label in (
            (initial.branch_id, root_id, "stale"),
            (other_branch_id, commit.revision_id, "other-branch"),
        ):
            with pytest.raises(ApplicationError, match="AI_RUN_BASE_REVISION_CONFLICT"):
                await CreateAIRun(uow)(
                    CreateAIRunRequest(
                        project_id=project_id, branch_id=branch_id, base_revision_id=revision_id,
                        thread_id=f"{label}-{uuid4().hex}", brief=_brief(),
                        idempotency_key=f"{label}-{uuid4().hex}",
                    )
                )
        async with engine.connect() as connection:
            assert await connection.scalar(
                select(func.count()).select_from(AIRunRow).where(
                    AIRunRow.project_id == project_id, AIRunRow.id.not_in([run_id])
                )
            ) == 0
        assert commit.revision_id != root_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_retry_child_uses_advanced_branch_head(test_postgres_dsn: str) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    run_id, project_id, root_id, uow, engine = await _seed_run(
        test_postgres_dsn, key=f"retry-head-{uuid4().hex}"
    )
    try:
        parent = await RequestAIRunAction(uow)(
            run_id=run_id, action="cancel", expected_version=0, idempotency_key="cancel-parent"
        )
        branch_id = parent.branch_id
        advanced = await CommitCommandBatch(PostgresUnitOfWork(create_session_factory(engine)))(
            CommitCommandBatchRequest(
                project_id=project_id,
                branch_id=branch_id,
                base_revision_id=root_id,
                commands=(AddTrackCommand(
                    command_id=uuid4(), actor_kind="human", client_sequence=0,
                    payload=AddTrackPayload(track=Track(
                        track_id=uuid4(), track_type=TrackType.INSTRUMENT,
                        name="Retry Head", role=TrackRole.HARMONY, instrument_ref="builtin:piano",
                    )),
                ),),
                actor_id="test", author_kind=AuthorKind.HUMAN, reason="RETRY_HEAD",
                idempotency_key=f"advance-{uuid4().hex}",
            )
        )
        child = await RequestAIRunAction(uow)(
            run_id=run_id,
            action="retry",
            expected_version=parent.version,
            idempotency_key="retry-after-advance",
        )
        assert child.base_revision_id == advanced.revision_id
        assert (await _run(uow, run_id)) == parent
    finally:
        await engine.dispose()


async def _run(uow: PostgresAIRunUnitOfWork, run_id: UUID):
    async with uow() as transaction:
        return await transaction.read_ai_run(run_id)
