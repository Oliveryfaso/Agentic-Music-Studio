from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from motif_forge.domain import create_root_state
from motif_forge.infrastructure.persistence.database import (
    _revision_from_row,
    _revision_values,
    create_postgres_engine,
    normalize_postgres_dsn,
)
from motif_forge.infrastructure.persistence.tables import (
    APP_SCHEMA,
    AIRunEventRow,
    Base,
    UsageLedgerRow,
)


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
        "app.candidate_snapshots",
        "app.preview_candidates",
        "app.approvals",
        "app.runs",
        "app.jobs",
        "app.run_events",
        "app.job_events",
        "app.outbox_events",
        "app.inbox_receipts",
        "app.artifacts",
        "app.feature_artifacts",
        "app.storage_events",
        "app.ai_runs",
        "app.composition_plans",
        "app.ai_run_events",
        "app.ai_model_request_reservations",
        "app.composition_materialization_receipts",
    }.issubset(Base.metadata.tables)


def test_raw_postgres_dsn_is_normalized_for_async_sqlalchemy() -> None:
    assert (
        normalize_postgres_dsn("postgresql://user:pass@localhost/db")
        == "postgresql+psycopg://user:pass@localhost/db"
    )


def test_sqlite_cannot_be_used_as_persistence_substitute() -> None:
    with pytest.raises(ValueError, match="PostgreSQL DSN"):
        create_postgres_engine("sqlite+aiosqlite:///:memory:")


def test_revision_jsonb_payload_round_trips_into_strict_domain_model() -> None:
    root = create_root_state(UUID(int=1), created_by="persistence-test")
    stored_values = _revision_values(root.revision)

    restored = _revision_from_row(SimpleNamespace(**stored_values))  # type: ignore[arg-type]

    assert restored == root.revision


def test_alembic_has_single_reversible_head() -> None:
    root = Path(__file__).resolve().parents[6]
    config = Config(root / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["20260820_0018"]
    migration = scripts.get_revision("20260813_0013")
    assert migration is not None
    assert callable(migration.module.upgrade)
    assert callable(migration.module.downgrade)
    receipt_migration = scripts.get_revision("20260813_0016")
    assert receipt_migration is not None
    assert callable(receipt_migration.module.upgrade)
    assert callable(receipt_migration.module.downgrade)
    style_pack_migration = scripts.get_revision("20260820_0017")
    assert style_pack_migration is not None
    assert callable(style_pack_migration.module.upgrade)
    assert callable(style_pack_migration.module.downgrade)
    candidate_lineage_migration = scripts.get_revision("20260820_0018")
    assert candidate_lineage_migration is not None
    assert callable(candidate_lineage_migration.module.upgrade)
    assert callable(candidate_lineage_migration.module.downgrade)


def test_ai_event_sequence_is_bigint_and_usage_cost_can_be_unknown() -> None:
    assert AIRunEventRow.__table__.c.sequence.type.__class__.__name__ == "BigInteger"
    assert UsageLedgerRow.__table__.c.estimated_cost_microusd.nullable is True
    assert "cost_status" in UsageLedgerRow.__table__.c
