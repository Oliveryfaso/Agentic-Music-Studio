"""Persist one immutable bounded piano plan per finite AI edit run."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "20261019_0027"
down_revision: str | None = "20261019_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "piano_accompaniment_plans",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.ai_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "(schema_version = 'piano-plan-record.v1' AND "
            "jsonb_typeof(payload) = 'object' AND "
            "payload->>'schema_version' = schema_version) IS TRUE",
            name="piano_accompaniment_plans_version_valid",
        ),
        schema="app",
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        populated = op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM app.piano_accompaniment_plans) "
                "OR EXISTS (SELECT 1 FROM app.ai_runs "
                "WHERE state_schema_version = 'piano-accompaniment-run.v1')"
            )
        )
        if populated:
            raise RuntimeError("cannot downgrade 0027 while semantic piano Runs or plans exist")
    op.drop_table("piano_accompaniment_plans", schema="app")
