"""Persist deterministic BPM/key analysis on normalized import Artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0007"
down_revision: str | None = "20260812_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("artifacts", "analysis", schema=SCHEMA)
