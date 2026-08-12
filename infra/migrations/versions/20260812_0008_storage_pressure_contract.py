"""Persist complete rebuild metadata and lifecycle timestamps."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0008"
down_revision: str | None = "20260812_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("artifacts", sa.Column("rebuild_recipe", jsonb), schema=SCHEMA)
    op.add_column(
        "artifacts",
        sa.Column(
            "protection_reasons",
            jsonb,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "artifacts", sa.Column("last_accessed_at", sa.DateTime(timezone=True)), schema=SCHEMA
    )
    op.add_column("artifacts", sa.Column("expires_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    op.add_column("artifacts", sa.Column("evicted_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    op.add_column("artifacts", sa.Column("rehydration_job_id", uuid), schema=SCHEMA)
    # Historical rows never stored a complete executable recipe. Keep them safe.
    op.execute(
        "UPDATE app.artifacts SET lifecycle_class = 'protected', recipe_hash = NULL "
        "WHERE lifecycle_class = 'rebuildable' AND rebuild_recipe IS NULL"
    )
    op.execute(
        "UPDATE app.artifacts SET last_accessed_at = created_at WHERE last_accessed_at IS NULL"
    )
    op.create_index(
        "ix_artifacts_availability_accessed",
        "artifacts",
        ["availability", "last_accessed_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "storage_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("operation_id", sa.String(200), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("route", sa.String(40), nullable=False),
        sa.Column("explanation_code", sa.String(120), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        sa.UniqueConstraint(
            "operation_id", "sequence", name="uq_storage_events_operation_sequence"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_storage_events_project_created",
        "storage_events",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM app.artifacts
                WHERE availability IN ('evicted', 'rehydrating')
                   OR rebuild_recipe IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade 20260812_0008 while rebuild lifecycle data exists';
            END IF;
        END $$
        """
    )
    op.drop_index("ix_storage_events_project_created", table_name="storage_events", schema=SCHEMA)
    op.drop_table("storage_events", schema=SCHEMA)
    op.drop_index("ix_artifacts_availability_accessed", table_name="artifacts", schema=SCHEMA)
    op.drop_column("artifacts", "rehydration_job_id", schema=SCHEMA)
    op.drop_column("artifacts", "evicted_at", schema=SCHEMA)
    op.drop_column("artifacts", "expires_at", schema=SCHEMA)
    op.drop_column("artifacts", "last_accessed_at", schema=SCHEMA)
    op.drop_column("artifacts", "protection_reasons", schema=SCHEMA)
    op.drop_column("artifacts", "rebuild_recipe", schema=SCHEMA)
