"""Persist finite S2 AI runs, immutable plans, events, and reservations."""
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0013"
down_revision: str | None = "20260812_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "ai_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "project_id", uuid, sa.ForeignKey("app.projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("branch_id", uuid, sa.ForeignKey("app.project_branches.id"), nullable=False),
        sa.Column(
            "base_revision_id", uuid, sa.ForeignKey("app.project_revisions.id"), nullable=False
        ),
        sa.Column("thread_id", sa.String(160), nullable=False),
        sa.Column("graph_topology_version", sa.String(80), nullable=False),
        sa.Column("state_schema_version", sa.String(80), nullable=False),
        sa.Column("brief", jsonb),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(160)),
        sa.Column("approval_assertion_hash", sa.String(64)),
        sa.Column("submitted_model_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost_status", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("cost_microusd", sa.BigInteger()),
        sa.Column("pricing_version", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "project_id", "idempotency_key", name="uq_ai_runs_project_idempotency_key"
        ),
        schema="app",
    )
    op.create_index("ix_ai_runs_project_status", "ai_runs", ["project_id", "status"], schema="app")
    op.create_table(
        "ai_run_approvals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "run_id", uuid, sa.ForeignKey("app.ai_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("assertion_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_ai_run_approvals_run"),
        schema="app",
    )
    op.create_table(
        "composition_plans",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "run_id", uuid, sa.ForeignKey("app.ai_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("plan", jsonb, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column("style_pack_version", sa.String(80), nullable=False),
        sa.Column("fallback_reason", sa.String(240)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "content_hash", name="uq_composition_plans_run_hash"),
        schema="app",
    )
    op.create_table(
        "ai_run_events",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", uuid, nullable=False, unique=True),
        sa.Column(
            "run_id", uuid, sa.ForeignKey("app.ai_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("phase", sa.String(80), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("dedupe_key", sa.String(240)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "event_type", "dedupe_key", name="uq_ai_run_events_dedupe"),
        schema="app",
    )
    op.create_index(
        "ix_ai_run_events_run_sequence", "ai_run_events", ["run_id", "sequence"], schema="app"
    )
    op.create_table(
        "ai_model_request_reservations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "run_id", uuid, sa.ForeignKey("app.ai_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("request_ordinal", sa.Integer(), nullable=False),
        sa.Column("request_kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider_operation_id", sa.String(200), unique=True),
        sa.Column("prompt_tokens", sa.BigInteger()),
        sa.Column("completion_tokens", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "run_id", "request_ordinal", name="uq_ai_model_request_reservations_ordinal"
        ),
        schema="app",
    )
    op.alter_column(
        "usage_ledger", "estimated_cost_microusd", nullable=True, schema="observability"
    )
    op.add_column(
        "usage_ledger",
        sa.Column("cost_status", sa.String(24), nullable=False, server_default="unknown"),
        schema="observability",
    )
    op.add_column(
        "usage_ledger", sa.Column("pricing_version", sa.String(80)), schema="observability"
    )
    op.execute(
        "UPDATE observability.usage_ledger SET cost_status = 'unknown', estimated_cost_microusd = NULL WHERE estimated_cost_microusd = 0"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE observability.usage_ledger SET estimated_cost_microusd = 0 WHERE estimated_cost_microusd IS NULL"
    )
    op.drop_column("usage_ledger", "pricing_version", schema="observability")
    op.drop_column("usage_ledger", "cost_status", schema="observability")
    op.alter_column(
        "usage_ledger",
        "estimated_cost_microusd",
        nullable=False,
        server_default="0",
        schema="observability",
    )
    op.drop_table("ai_model_request_reservations", schema="app")
    op.drop_index("ix_ai_run_events_run_sequence", table_name="ai_run_events", schema="app")
    op.drop_table("ai_run_events", schema="app")
    op.drop_table("composition_plans", schema="app")
    op.drop_table("ai_run_approvals", schema="app")
    op.drop_index("ix_ai_runs_project_status", table_name="ai_runs", schema="app")
    op.drop_table("ai_runs", schema="app")
