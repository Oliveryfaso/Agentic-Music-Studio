from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection, sql

TEST_POSTGRES_DSN_ENV = "MOTIF_FORGE_TEST_POSTGRES_DSN"


@dataclass(frozen=True, slots=True)
class IsolatedPostgresSchemas:
    primary: str
    secondary: str


@pytest.fixture(scope="session")
def test_postgres_dsn() -> Iterator[str]:
    """Return the opt-in test DSN without ever falling back to a local database."""

    dsn = os.environ.get(TEST_POSTGRES_DSN_ENV, "").strip()
    if not dsn:
        pytest.skip(
            f"real PostgreSQL integration requires {TEST_POSTGRES_DSN_ENV}; "
            "SQLite and implicit local credentials are intentionally unsupported"
        )
    yield dsn


@pytest_asyncio.fixture
async def isolated_postgres_schemas(
    test_postgres_dsn: str,
) -> AsyncIterator[IsolatedPostgresSchemas]:
    """Allocate unique schema names and remove only those exact schemas afterwards."""

    token = uuid4().hex
    schemas = IsolatedPostgresSchemas(
        primary=f"motif_forge_it_a_{token}",
        secondary=f"motif_forge_it_b_{token}",
    )
    try:
        yield schemas
    finally:
        connection = await AsyncConnection.connect(test_postgres_dsn, autocommit=True)
        async with connection:
            for schema in (schemas.primary, schemas.secondary):
                await connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
