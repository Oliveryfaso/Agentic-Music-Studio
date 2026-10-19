from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from motif_forge.application.errors import ApplicationError
from motif_forge.infrastructure.persistence.piano_plans import PostgresPianoPlanStore


def _record() -> dict[str, object]:
    return {
        "schema_version": "piano-plan-record.v1",
        "plan": {"schema_version": "accompaniment-plan.v1", "summary": "前疏后密", "bars": []},
        "provider": "deepseek",
        "requested_model": "deepseek-v4-flash",
        "model": "deepseek-v4-flash",
        "prompt_version": "piano-accompaniment-prompt.v1",
        "usage": {
            "status": "known",
            "prompt_tokens": 20,
            "completion_tokens": 30,
            "total_tokens": 50,
        },
        "operation_id": "piano-plan-1",
    }


def _factory(payload: dict[str, object] | None, *, save: bool = False):
    read_result = SimpleNamespace(scalar_one_or_none=lambda: payload, scalar_one=lambda: payload)
    session = MagicMock()
    session.execute = AsyncMock(side_effect=([None, read_result] if save else [read_result]))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock()
    transaction.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value = transaction
    return MagicMock(return_value=session), session, transaction


@pytest.mark.asyncio
async def test_saved_plan_replay_returns_detached_immutable_value() -> None:
    record = _record()
    factory, session, _ = _factory(record, save=True)
    store = PostgresPianoPlanStore(factory)
    restored = await store.save(UUID(int=1), record)
    assert restored == record
    assert restored is not record
    restored["plan"]["summary"] = "caller mutation"
    assert record["plan"]["summary"] == "前疏后密"
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_conflicting_replay_fails_without_overwriting_result() -> None:
    factory, _, transaction = _factory(_record(), save=True)
    changed = {**_record(), "operation_id": "different-paid-operation"}
    with pytest.raises(ApplicationError) as error:
        await PostgresPianoPlanStore(factory).save(UUID(int=1), changed)
    assert error.value.code == "PIANO_PLAN_RECORD_CONFLICT"
    assert transaction.__aexit__.await_args.args[0] is ApplicationError


@pytest.mark.asyncio
async def test_read_missing_or_present_plan_does_not_mutate_ledger() -> None:
    factory, session, _ = _factory(None)
    assert await PostgresPianoPlanStore(factory).read(UUID(int=1)) is None
    assert session.execute.await_count == 1
    record = _record()
    factory, _, _ = _factory(record)
    assert await PostgresPianoPlanStore(factory).read(UUID(int=1)) == record


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["prompt", "reasoning_content", "api_key", "authorization"])
async def test_secret_or_raw_reasoning_record_is_rejected_before_storage(field: str) -> None:
    factory, session, _ = _factory(None)
    record = {**_record(), "extra": {field: "must not persist"}}
    with pytest.raises(ApplicationError) as error:
        await PostgresPianoPlanStore(factory).save(UUID(int=1), record)
    assert error.value.code == "PIANO_PLAN_RECORD_INVALID"
    session.execute.assert_not_awaited()


def test_migration_creates_piano_plan_table_without_touching_existing_runs() -> None:
    from io import StringIO
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from motif_forge.infrastructure.persistence.tables import PianoAccompanimentPlanRow

    repository = Path(__file__).resolve().parents[6]
    output = StringIO()
    config = Config(repository / "alembic.ini", output_buffer=output)
    command.upgrade(config, "20261019_0026:20261019_0027", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE app.piano_accompaniment_plans" in sql
    assert "FOREIGN KEY(run_id) REFERENCES app.ai_runs (id) ON DELETE CASCADE" in sql
    assert "piano-plan-record.v1" in sql
    assert "UPDATE app.ai_runs" not in sql
    assert str(PianoAccompanimentPlanRow.__table__.schema) == "app"


def test_populated_semantic_run_blocks_downgrade_even_before_a_plan_exists(monkeypatch) -> None:
    from pathlib import Path
    from unittest.mock import Mock

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    repository = Path(__file__).resolve().parents[6]
    migration = (
        ScriptDirectory.from_config(Config(repository / "alembic.ini"))
        .get_revision("20261019_0027")
        .module
    )
    bind = Mock()
    bind.scalar.return_value = True
    drop = Mock()
    monkeypatch.setattr(migration.context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "drop_table", drop)
    with pytest.raises(RuntimeError, match="semantic piano Runs or plans"):
        migration.downgrade()
    assert "state_schema_version" in str(bind.scalar.call_args.args[0])
    drop.assert_not_called()
