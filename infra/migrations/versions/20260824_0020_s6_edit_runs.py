"""Add strict persisted Edit Run identity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0020"
down_revision: str | None = "20260821_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_runs",
        sa.Column("run_type", sa.String(16), nullable=False, server_default="generate"),
        schema="app",
    )
    op.add_column(
        "ai_runs",
        sa.Column("edit_request", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="app",
    )
    op.create_check_constraint(
        "ai_runs_type_payload_valid",
        "ai_runs",
        "(run_type = 'generate' AND edit_request IS NULL) OR "
        "(run_type = 'edit' AND brief IS NULL AND edit_request IS NOT NULL)",
        schema="app",
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        populated = op.get_bind().scalar(
            sa.text("SELECT count(*) FROM app.ai_runs WHERE run_type = 'edit'")
        )
        if populated:
            raise RuntimeError("cannot downgrade 0020 while persisted Edit Runs exist")
    op.drop_constraint("ai_runs_type_payload_valid", "ai_runs", schema="app", type_="check")
    op.drop_column("ai_runs", "edit_request", schema="app")
    op.drop_column("ai_runs", "run_type", schema="app")
