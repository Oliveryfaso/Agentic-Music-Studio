"""Persist Edit Preview waiting identity and human decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0021"
down_revision: str | None = "20260824_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_runs",
        sa.Column("pending_preview_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="app",
    )
    op.create_foreign_key(
        "fk_ai_runs_pending_preview",
        "ai_runs",
        "preview_candidates",
        ["pending_preview_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_table(
        "ai_run_edit_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preview_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("expected_candidate_content_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("assertion_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["app.ai_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preview_id"], ["app.preview_candidates.id"]),
        sa.UniqueConstraint("run_id", name="uq_ai_run_edit_decisions_run"),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("ai_run_edit_decisions", schema="app")
    op.drop_constraint("fk_ai_runs_pending_preview", "ai_runs", schema="app", type_="foreignkey")
    op.drop_column("ai_runs", "pending_preview_id", schema="app")
