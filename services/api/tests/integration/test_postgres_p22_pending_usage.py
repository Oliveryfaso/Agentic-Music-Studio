"""Real PG proof that pending provider submissions never masquerade as known zero usage."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from langchain_core.messages import HumanMessage
from motif_forge.agent.planner import (
    PersistentProviderBudgetLedger,
    PlannerError,
    ProviderBudgetExceeded,
)
from motif_forge.application.ai_runs import (
    ReadAIRun,
    ReadAIRunByThreadId,
    ReadAIRunProjection,
    RecordModelUsage,
    ReserveModelRequest,
)
from motif_forge.application.edit_runs import CreateEditAIRun, CreateEditAIRunRequest
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.ai_runs import (
    AIRun,
    CostStatus,
    EditRunRequest,
    ModelRequestKind,
    ModelUsageStatus,
)
from motif_forge.domain.commands import Selection
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.piano_requests import PianoSemanticRequest
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.run_inspection import PostgresRunInspectionStore
from motif_forge.infrastructure.persistence.tables import AIRunRow, ModelRequestReservationRow
from motif_forge.providers.deepseek import DeepSeekJsonClient
from sqlalchemy import select, text


def _upgrade(dsn: str) -> None:
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(Path(__file__).resolve().parents[4] / "alembic.ini"), "head")


async def _seed(dsn: str, *, max_requests: int = 1):
    await asyncio.to_thread(_upgrade, dsn)
    engine = create_postgres_engine(dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name="Pending usage " + uuid4().hex,
            actor_id="p22-usage-test",
            idempotency_key=uuid4().hex,
        )
    )
    ai = PostgresAIRunUnitOfWork(sessions)
    semantic = PianoSemanticRequest(intent="增加低音钢琴伴奏", mode="append")
    run = await CreateEditAIRun(ai)(
        CreateEditAIRunRequest(
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            thread_id="piano-usage-" + uuid4().hex,
            edit_request=EditRunRequest(
                intent=semantic.intent, selection=Selection(), piano_request=semantic
            ),
            idempotency_key=uuid4().hex,
            max_model_requests=max_requests,
            max_total_tokens=12000,
        )
    )
    return run, ai, sessions, engine


async def _cleanup(engine, run: AIRun) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM app.outbox_events WHERE aggregate_id=:run"), {"run": run.run_id}
        )
        await connection.execute(
            text("DELETE FROM app.audit_events WHERE project_id=:project"),
            {"project": run.project_id},
        )
        await connection.execute(
            text("DELETE FROM app.projects WHERE id=:project"), {"project": run.project_id}
        )
    await engine.dispose()


async def _all_reads(ai, sessions, run: AIRun):
    # Fresh transactions/readers model a restart, not an in-memory projected object.
    direct = await ReadAIRun(ai)(run.run_id)
    by_thread = await ReadAIRunByThreadId(ai)(run.thread_id)
    projected = (await ReadAIRunProjection(ai)(run.run_id)).run
    inspector = await PostgresRunInspectionStore(sessions).read_run_inspection(run.run_id)
    assert inspector is not None
    for value in (direct, by_thread, projected):
        assert value.submitted_model_requests == inspector.usage.submitted_model_requests
        assert value.model_usage_status.value == inspector.usage.usage_status
        assert value.total_tokens == inspector.usage.total_tokens
        assert value.prompt_tokens == inspector.usage.prompt_tokens
        assert value.completion_tokens == inspector.usage.completion_tokens
        assert value.cost.status.value == inspector.usage.cost_status
    return direct, by_thread, projected, inspector


class _Output(DomainModel):
    result: str


@pytest.mark.asyncio
async def test_timeout_pending_submission_reads_unknown_after_restart_and_cannot_resubmit(
    test_postgres_dsn,
):
    run, ai, sessions, engine = await _seed(test_postgres_dsn)
    submitted = []

    async def fail(request):
        submitted.append(1)
        raise httpx.ReadTimeout("simulated post-submission timeout", request=request)

    try:
        ledger = PersistentProviderBudgetLedger(
            ai, run_id=run.run_id, max_requests=1, max_total_tokens=12000
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
            client = DeepSeekJsonClient(
                api_key="test-fake-only",
                http_client=http,
                run_id=run.run_id,
                budget_ledger=ledger,
                max_attempts=1,
            )
            with pytest.raises(PlannerError) as error:
                await client.complete_json(
                    messages=[HumanMessage(content="Return JSON")],
                    output_model=_Output,
                    thinking="disabled",
                    max_tokens=256,
                )
            assert error.value.code == "DEEPSEEK_TIMEOUT"
            direct, by_thread, projected, inspector = await _all_reads(
                PostgresAIRunUnitOfWork(sessions), sessions, run
            )
            for value in (direct, by_thread, projected):
                assert value.submitted_model_requests == 1
                assert value.model_usage_status is ModelUsageStatus.UNKNOWN
                assert value.total_tokens is None
                assert value.prompt_tokens is None
                assert value.completion_tokens is None
                assert value.prompt_cache_hit_tokens is None
                assert value.prompt_cache_miss_tokens is None
                assert value.reasoning_tokens is None
                assert value.cost.status is CostStatus.UNKNOWN
                assert value.cost.amount_microusd is None
            assert inspector.usage.total_tokens is None
            async with sessions() as session:
                raw = (
                    await session.execute(select(AIRunRow).where(AIRunRow.id == run.run_id))
                ).scalar_one()
                reservation = (
                    await session.execute(
                        select(ModelRequestReservationRow).where(
                            ModelRequestReservationRow.run_id == run.run_id
                        )
                    )
                ).scalar_one()
                assert raw.total_tokens == 0 and raw.model_usage_status == "known"
                assert reservation.status == "reserved" and reservation.usage_status is None
            with pytest.raises(ProviderBudgetExceeded):
                await client.complete_json(
                    messages=[HumanMessage(content="Return JSON")],
                    output_model=_Output,
                    thinking="disabled",
                    max_tokens=256,
                )
            assert submitted == [1]
    finally:
        await _cleanup(engine, run)


@pytest.mark.asyncio
async def test_observed_zero_receipt_restores_known_real_zero_in_all_readers(test_postgres_dsn):
    run, ai, sessions, engine = await _seed(test_postgres_dsn)
    try:
        reservation = await ReserveModelRequest(ai)(
            run_id=run.run_id, kind=ModelRequestKind.INITIAL
        )
        pending = await ReadAIRun(ai)(run.run_id)
        assert pending.model_usage_status is ModelUsageStatus.UNKNOWN
        assert pending.total_tokens is None
        await RecordModelUsage(ai)(
            run_id=run.run_id,
            reservation_id=reservation.reservation_id,
            provider_operation_id="zero-" + uuid4().hex,
            usage_status=ModelUsageStatus.KNOWN,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            prompt_cache_hit_tokens=0,
            prompt_cache_miss_tokens=0,
            reasoning_tokens=0,
        )
        direct, by_thread, projected, inspector = await _all_reads(ai, sessions, run)
        for value in (direct, by_thread, projected):
            assert value.submitted_model_requests == 1
            assert value.model_usage_status is ModelUsageStatus.KNOWN
            assert value.total_tokens == value.prompt_tokens == value.completion_tokens == 0
            assert value.reasoning_tokens == 0
        assert inspector.usage.usage_status == "known" and inspector.usage.total_tokens == 0
    finally:
        await _cleanup(engine, run)


@pytest.mark.asyncio
async def test_pending_second_submission_does_not_destroy_prior_partial_facts(test_postgres_dsn):
    run, ai, sessions, engine = await _seed(test_postgres_dsn, max_requests=2)
    try:
        first = await ReserveModelRequest(ai)(run_id=run.run_id, kind=ModelRequestKind.INITIAL)
        await RecordModelUsage(ai)(
            run_id=run.run_id,
            reservation_id=first.reservation_id,
            provider_operation_id="partial-" + uuid4().hex,
            usage_status=ModelUsageStatus.PARTIAL,
            prompt_tokens=7,
            completion_tokens=3,
            total_tokens=10,
            prompt_cache_hit_tokens=None,
            prompt_cache_miss_tokens=7,
            reasoning_tokens=None,
        )
        second = await ReserveModelRequest(ai)(
            run_id=run.run_id, kind=ModelRequestKind.TRANSPORT_RETRY
        )
        pending, _, _, _ = await _all_reads(ai, sessions, run)
        assert pending.model_usage_status is ModelUsageStatus.UNKNOWN
        assert pending.total_tokens is None and pending.prompt_tokens is None
        async with sessions() as session:
            raw = (
                await session.execute(select(AIRunRow).where(AIRunRow.id == run.run_id))
            ).scalar_one()
            assert raw.total_tokens == 10 and raw.prompt_tokens == 7
            assert raw.model_usage_status == "partial" and raw.reasoning_tokens is None
        await RecordModelUsage(ai)(
            run_id=run.run_id,
            reservation_id=second.reservation_id,
            provider_operation_id="known-" + uuid4().hex,
            usage_status=ModelUsageStatus.KNOWN,
            prompt_tokens=11,
            completion_tokens=5,
            total_tokens=16,
            prompt_cache_hit_tokens=0,
            prompt_cache_miss_tokens=11,
            reasoning_tokens=0,
        )
        direct, _, _, inspector = await _all_reads(ai, sessions, run)
        assert direct.model_usage_status is ModelUsageStatus.PARTIAL
        assert (
            direct.prompt_tokens == 18
            and direct.completion_tokens == 8
            and direct.total_tokens == 26
        )
        assert direct.reasoning_tokens is None and direct.prompt_cache_hit_tokens is None
        assert direct.prompt_cache_miss_tokens == 18
        assert inspector.usage.total_tokens == 26 and inspector.usage.usage_status == "partial"
    finally:
        await _cleanup(engine, run)
