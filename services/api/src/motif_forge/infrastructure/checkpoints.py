"""PostgreSQL-backed LangGraph checkpoint lifecycle."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from pydantic import SecretStr

CHECKPOINT_SCHEMA = "motif_forge_graph"
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _plain_dsn(dsn: SecretStr | str) -> str:
    value = dsn.get_secret_value() if isinstance(dsn, SecretStr) else dsn
    if not value.strip():
        raise ValueError("PostgreSQL DSN must not be empty")
    return value


@asynccontextmanager
async def postgres_checkpointer(
    dsn: SecretStr | str,
    *,
    schema: str = CHECKPOINT_SCHEMA,
    setup: bool = True,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open one async saver in an isolated schema and close it with the app lifespan.

    ``setup`` delegates idempotent checkpoint-table migrations to LangGraph. Project
    facts remain in application tables and never depend on this schema.
    """

    if _SAFE_IDENTIFIER.fullmatch(schema) is None:
        raise ValueError("Checkpoint schema must be a safe PostgreSQL identifier")

    connection = await AsyncConnection.connect(
        _plain_dsn(dsn),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    async with connection:
        await connection.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )
        await connection.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
        )
        saver = AsyncPostgresSaver(connection)
        if setup:
            await saver.setup()
        yield saver
