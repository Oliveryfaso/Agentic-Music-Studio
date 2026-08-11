from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any

import pytest
from motif_forge.infrastructure import checkpoints


class FakeConnection(AbstractAsyncContextManager["FakeConnection"]):
    def __init__(self) -> None:
        self.executed: list[object] = []
        self.closed = False

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.closed = True

    async def execute(self, query: object) -> None:
        self.executed.append(query)


class FakeAsyncConnection:
    connection = FakeConnection()
    received_dsn: str | None = None

    @classmethod
    async def connect(cls, dsn: str, **kwargs: Any) -> FakeConnection:
        del kwargs
        cls.received_dsn = dsn
        return cls.connection


class FakeSaver:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.setup_called = False

    async def setup(self) -> None:
        self.setup_called = True


@pytest.mark.asyncio
async def test_postgres_checkpointer_uses_isolated_schema_and_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncConnection.connection = FakeConnection()
    monkeypatch.setattr(checkpoints, "AsyncConnection", FakeAsyncConnection)
    monkeypatch.setattr(checkpoints, "AsyncPostgresSaver", FakeSaver)

    async with checkpoints.postgres_checkpointer("postgresql://safe-test") as saver:
        assert isinstance(saver, FakeSaver)
        assert saver.setup_called is True
        assert len(saver.connection.executed) == 2

    assert FakeAsyncConnection.received_dsn == "postgresql://safe-test"
    assert FakeAsyncConnection.connection.closed is True


@pytest.mark.asyncio
async def test_postgres_checkpointer_rejects_unsafe_schema_before_connecting() -> None:
    with pytest.raises(ValueError, match="safe PostgreSQL identifier"):
        async with checkpoints.postgres_checkpointer(
            "postgresql://safe-test", schema="bad;drop schema public"
        ):
            pytest.fail("unsafe schema must not yield a saver")
