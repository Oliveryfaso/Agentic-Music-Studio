"""Add bounded Job execution and leased Outbox delivery metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0005"
down_revision: str | None = "20260811_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        schema=SCHEMA,
    )
    op.add_column("jobs", sa.Column("deadline_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    op.execute("UPDATE app.jobs SET deadline_at = created_at + interval '15 minutes'")
    op.alter_column("jobs", "deadline_at", nullable=False, schema=SCHEMA)
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    op.add_column("jobs", sa.Column("lease_owner", sa.String(160)), schema=SCHEMA)
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    op.add_column(
        "jobs",
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "jobs_attempts_within_limit",
        "jobs",
        "attempts >= 0 AND attempts <= max_attempts AND max_attempts BETWEEN 1 AND 5",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "jobs_progress_range",
        "jobs",
        "progress_percent BETWEEN 0 AND 100",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "jobs_lease_pair",
        "jobs",
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
        schema=SCHEMA,
    )

    op.add_column(
        "outbox_events",
        sa.Column("available_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    op.execute("UPDATE app.outbox_events SET available_at = created_at")
    op.alter_column("outbox_events", "available_at", nullable=False, schema=SCHEMA)
    op.add_column("outbox_events", sa.Column("lease_owner", sa.String(160)), schema=SCHEMA)
    op.add_column(
        "outbox_events", sa.Column("lease_expires_at", sa.DateTime(timezone=True)), schema=SCHEMA
    )
    op.add_column("outbox_events", sa.Column("last_error_code", sa.String(100)), schema=SCHEMA)
    op.create_index(
        "ix_outbox_events_dispatchable",
        "outbox_events",
        ["status", "available_at", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_dispatchable", table_name="outbox_events", schema=SCHEMA)
    op.drop_column("outbox_events", "last_error_code", schema=SCHEMA)
    op.drop_column("outbox_events", "lease_expires_at", schema=SCHEMA)
    op.drop_column("outbox_events", "lease_owner", schema=SCHEMA)
    op.drop_column("outbox_events", "available_at", schema=SCHEMA)

    op.drop_constraint("jobs_lease_pair", "jobs", type_="check", schema=SCHEMA)
    op.drop_constraint("jobs_progress_range", "jobs", type_="check", schema=SCHEMA)
    op.drop_constraint("jobs_attempts_within_limit", "jobs", type_="check", schema=SCHEMA)
    op.drop_column("jobs", "progress_percent", schema=SCHEMA)
    op.drop_column("jobs", "lease_expires_at", schema=SCHEMA)
    op.drop_column("jobs", "lease_owner", schema=SCHEMA)
    op.drop_column("jobs", "heartbeat_at", schema=SCHEMA)
    op.drop_column("jobs", "deadline_at", schema=SCHEMA)
    op.drop_column("jobs", "max_attempts", schema=SCHEMA)
