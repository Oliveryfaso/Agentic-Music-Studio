"""Add durable approved-Plan materialization receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0016"
down_revision: str | None = "20260813_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "composition_materialization_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_content_hash", sa.String(64), nullable=False),
        sa.Column("plan_hash_version", sa.String(48), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("assertion_hash", sa.String(64), nullable=False),
        sa.Column("candidate_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preview_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("style_pack_version", sa.String(80), nullable=False),
        sa.Column("compiler_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("seed BETWEEN 0 AND 2147483647", name="receipt_seed_range"),
        sa.CheckConstraint(
            "schema_version = 'composition-materialization-receipt.v1'",
            name="receipt_schema_supported",
        ),
        sa.CheckConstraint(
            "plan_hash_version IN ('composition-plan-hash.rounded-v1', "
            "'composition-plan-hash.lossless-v2')",
            name="receipt_plan_hash_version_supported",
        ),
        sa.CheckConstraint(
            "style_pack_version = 'synth-ambient.v1'", name="receipt_style_pack_supported"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["app.ai_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["app.composition_plans.id"]),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["app.candidate_snapshots.id"]),
        sa.ForeignKeyConstraint(["preview_id"], ["app.preview_candidates.id"]),
        sa.ForeignKeyConstraint(["revision_id"], ["app.project_revisions.id"]),
        sa.ForeignKeyConstraint(["command_batch_id"], ["app.command_batches.id"]),
        sa.UniqueConstraint(
            "run_id",
            "plan_id",
            "plan_content_hash",
            "seed",
            name="uq_composition_materialization_logical_identity",
        ),
        schema="app",
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        count = op.get_bind().scalar(
            sa.text("SELECT count(*) FROM app.composition_materialization_receipts")
        )
        if count:
            raise RuntimeError(
                "cannot downgrade 0016 while durable composition materialization receipts exist"
            )
    op.drop_table("composition_materialization_receipts", schema="app")
