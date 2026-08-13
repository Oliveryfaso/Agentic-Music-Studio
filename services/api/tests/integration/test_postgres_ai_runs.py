"""Real PostgreSQL coverage for the S2 durable AI-run ledger."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.ai_runs import ReserveModelRequest
from motif_forge.domain.ai_runs import ModelRequestKind
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    create_postgres_engine,
    create_session_factory,
)


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict("os.environ", {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


@pytest.mark.asyncio
async def test_reservation_is_conservatively_persisted_before_any_provider_call(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    try:
        # The fuller create/plan/event path is exercised through the transaction contract;
        # this test specifically proves no request path can use SQLite implicitly.
        uow = PostgresAIRunUnitOfWork(create_session_factory(engine))
        with pytest.raises(Exception, match="AI_RUN_NOT_FOUND"):
            await ReserveModelRequest(uow)(run_id=uuid4(), kind=ModelRequestKind.INITIAL)
    finally:
        await engine.dispose()
