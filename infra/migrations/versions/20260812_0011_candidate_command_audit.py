"""Persist candidate generation commands for approved Revision audit."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0011"
down_revision: str | None = "20260812_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_snapshots",
        sa.Column(
            "commands",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="app",
    )
    op.alter_column("candidate_snapshots", "commands", server_default=None, schema="app")


def downgrade() -> None:
    op.drop_column("candidate_snapshots", "commands", schema="app")
