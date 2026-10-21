"""SQL shape and merge contracts; a real PostgreSQL boundary is tested separately."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from motif_forge.infrastructure.persistence.piano_recovery import PostgresPianoRecoveryStore
from sqlalchemy.dialects import postgresql

PROJECT, BRANCH, BASE = UUID(int=1), UUID(int=2), UUID(int=3)
NOW = datetime(2026, 10, 21, tzinfo=UTC)


def _source(thread: str | None, *, preview: int | None, age: int = 0, **extra):
    return {
        "thread_id": thread,
        "branch_id": BRANCH,
        "base_revision_id": BASE,
        "created_at": NOW - timedelta(seconds=age),
        **(
            {
                "preview_id": UUID(int=preview),
                "candidate_content_hash": "a" * 64,
                "expires_at": NOW + timedelta(hours=1),
            }
            if preview is not None
            else {}
        ),
        **extra,
    }


def _factory(previews=(), early=()):
    def result(rows):
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result(previews), result(early)])
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session), session


async def _read(factory, *, limit=11):
    return await PostgresPianoRecoveryStore(factory).list_sources(
        project_id=PROJECT,
        branch_id=BRANCH,
        now=NOW,
        limit=limit,
    )


def _sql(statement):
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_empty_discovery_executes_only_two_bounded_selects():
    factory, session = _factory()
    assert await _read(factory) == ()
    assert session.execute.await_count == 2
    for call in session.execute.await_args_list:
        statement = call.args[0]
        assert statement.is_select
        assert "LIMIT 11" in _sql(statement)
        assert "FOR UPDATE" not in _sql(statement)
    session.begin.assert_not_called()
    session.commit.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_preview_query_preserves_baseline_and_orphans_with_scoped_outer_joins():
    factory, session = _factory()
    await _read(factory)
    statement = session.execute.await_args_list[0].args[0]
    sql = _sql(statement)
    assert set(statement.selected_columns.keys()) == {
        "thread_id",
        "branch_id",
        "base_revision_id",
        "created_at",
        "preview_id",
        "candidate_content_hash",
        "expires_at",
    }
    assert "SELECT DISTINCT" in sql
    assert "LEFT OUTER JOIN app.idempotency_records" in sql
    assert "LEFT OUTER JOIN app.jobs" in sql
    assert "LEFT OUTER JOIN app.runs" in sql
    assert "LEFT OUTER JOIN app.ai_runs" in sql
    assert "idempotency_records.resource_id = app.preview_candidates.id" in sql
    assert "idempotency_records.operation = 'preview.create-from-commands.v1'" in sql
    assert "idempotency_records.idempotency_key LIKE 'piano-preview:%%'" in sql
    assert "idempotency_records.idempotency_key || ':baseline'" in sql
    assert "idempotency_records.idempotency_key || ':piano'" in sql
    assert "app.jobs.project_id = app.preview_candidates.project_id" in sql
    assert "app.runs.project_id = app.preview_candidates.project_id" in sql
    assert "app.runs.run_type = 'parent.piano_preview.v1'" in sql
    assert "app.ai_runs.project_id = app.preview_candidates.project_id" in sql
    assert "app.ai_runs.branch_id = app.preview_candidates.branch_id" in sql
    assert "app.ai_runs.base_revision_id = app.preview_candidates.base_revision_id" in sql
    assert "coalesce(app.runs.thread_id, app.ai_runs.thread_id)" in sql
    assert "app.preview_candidates.status = 'pending'" in sql
    assert "app.preview_candidates.expires_at >" in sql
    assert "app.preview_candidates.branch_id = '00000000-0000-0000-0000-000000000002'" in sql
    assert "app.preview_candidates.project_id = '00000000-0000-0000-0000-000000000001'" in sql
    assert "app.idempotency_records.id IS NOT NULL OR app.ai_runs.id IS NOT NULL" in sql
    assert sql.index("app.preview_candidates.status = 'pending'") < sql.index("LIMIT 11")
    assert "DESC NULLS LAST" in sql
    for large_field in ("candidate_ir", "arrangement_ir", "input_payload", "result_payload"):
        assert large_field not in sql


@pytest.mark.asyncio
async def test_early_semantic_query_requires_piano_object_and_excludes_any_materialized_preview():
    factory, session = _factory()
    await _read(factory)
    statement = session.execute.await_args_list[1].args[0]
    sql = _sql(statement)
    assert set(statement.selected_columns.keys()) == {
        "thread_id",
        "branch_id",
        "base_revision_id",
        "created_at",
        "early_phase",
    }
    assert "app.ai_runs.project_id = '00000000-0000-0000-0000-000000000001'" in sql
    assert "app.ai_runs.branch_id = '00000000-0000-0000-0000-000000000002'" in sql
    assert "app.ai_runs.run_type = 'edit'" in sql
    assert "app.ai_runs.status IN ('queued', 'planning')" in sql
    assert "jsonb_typeof(app.ai_runs.edit_request['piano_request']) = 'object'" in sql
    assert "NOT (EXISTS (SELECT" in sql
    assert "app.preview_candidates.source_run_id = app.ai_runs.id" in sql
    assert "preview_candidates.status" not in sql
    assert "preview_candidates.expires_at" not in sql
    assert "app.ai_runs.created_at DESC, app.ai_runs.thread_id DESC" in sql
    assert sql.index("app.ai_runs.branch_id =") < sql.index("LIMIT 11")
    assert "input_payload" not in sql
    assert "candidate_ir" not in sql


@pytest.mark.asyncio
async def test_merges_by_creation_and_thread_deduplicates_jobs_and_preserves_each_orphan():
    duplicate = _source("piano-b", preview=10, age=1)
    factory, _ = _factory(
        previews=(
            duplicate,
            duplicate,
            _source(None, preview=11, age=3),
            _source(None, preview=12, age=4),
        ),
        early=(
            _source("piano-a", preview=None, age=1, early_phase="planning"),
            _source("piano-c", preview=None, age=1, early_phase="queued"),
        ),
    )
    found = await _read(factory)
    assert [(item.thread_id, item.preview_id) for item in found] == [
        ("piano-c", None),
        ("piano-b", UUID(int=10)),
        ("piano-a", None),
        (None, UUID(int=11)),
        (None, UUID(int=12)),
    ]
    assert found[1].candidate_content_hash == "a" * 64
    assert found[1].base_revision_id == BASE
    assert found[1].expires_at == NOW + timedelta(hours=1)


@pytest.mark.asyncio
async def test_combined_limit_is_applied_after_merge_and_thread_deduplication():
    factory, _ = _factory(
        previews=(_source("piano-b", preview=10, age=2), _source("piano-a", preview=11, age=3)),
        early=(
            _source("piano-c", preview=None, age=1, early_phase="queued"),
            _source("piano-b", preview=None, age=4, early_phase="planning"),
        ),
    )
    assert [item.thread_id for item in await _read(factory, limit=2)] == ["piano-c", "piano-b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, 12])
async def test_limit_outside_directory_budget_is_rejected_before_query(limit):
    factory, session = _factory()
    with pytest.raises(ValueError, match="between 1 and 11"):
        await _read(factory, limit=limit)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_source_limit_is_retained_in_both_sql_statements():
    factory, session = _factory()
    await _read(factory, limit=1)
    assert len(session.execute.await_args_list) == 2
    assert all("LIMIT 1" in _sql(call.args[0]) for call in session.execute.await_args_list)
