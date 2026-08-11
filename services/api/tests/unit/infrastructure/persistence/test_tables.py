from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from motif_forge.infrastructure.persistence.database import (
    create_postgres_engine,
    normalize_postgres_dsn,
)
from motif_forge.infrastructure.persistence.tables import APP_SCHEMA, Base


def test_business_tables_are_isolated_in_app_schema() -> None:
    assert Base.metadata.schema == APP_SCHEMA
    assert {
        "app.projects",
        "app.project_branches",
        "app.project_revisions",
        "app.command_batches",
        "app.revision_commands",
        "app.idempotency_records",
        "app.audit_events",
    }.issubset(Base.metadata.tables)


def test_raw_postgres_dsn_is_normalized_for_async_sqlalchemy() -> None:
    assert (
        normalize_postgres_dsn("postgresql://user:pass@localhost/db")
        == "postgresql+psycopg://user:pass@localhost/db"
    )


def test_sqlite_cannot_be_used_as_persistence_substitute() -> None:
    with pytest.raises(ValueError, match="PostgreSQL DSN"):
        create_postgres_engine("sqlite+aiosqlite:///:memory:")


def test_alembic_has_single_reversible_head() -> None:
    root = Path(__file__).resolve().parents[6]
    config = Config(root / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["20260811_0001"]
    migration = scripts.get_revision("20260811_0001")
    assert migration is not None
    assert callable(migration.module.upgrade)
    assert callable(migration.module.downgrade)
