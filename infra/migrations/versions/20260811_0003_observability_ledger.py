"""Add persistent Trace/Span and idempotent model Usage Ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0003"
down_revision: str | None = "20260811_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "observability"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "traces",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", sa.String(160), nullable=False, unique=True),
        sa.Column("thread_id", sa.String(160), nullable=False),
        sa.Column("trace_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "trace_spans",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("trace_id", uuid, nullable=False),
        sa.Column("operation_id", sa.String(200), nullable=False),
        sa.Column("run_id", sa.String(160), nullable=False),
        sa.Column("node", sa.String(120), nullable=False),
        sa.Column("span_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider", sa.String(80)),
        sa.Column("model", sa.String(120)),
        sa.Column("prompt_version", sa.String(80)),
        sa.Column("schema_version", sa.String(80)),
        sa.Column("thinking_mode", sa.String(16)),
        sa.Column("safe_summary", jsonb, nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], [f"{SCHEMA}.traces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("operation_id", name="uq_trace_spans_operation_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_trace_spans_run_started",
        "trace_spans",
        ["run_id", "started_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "usage_ledger",
        sa.Column("operation_id", sa.String(200), primary_key=True),
        sa.Column("trace_span_id", uuid, nullable=False),
        sa.Column("run_id", sa.String(160), nullable=False),
        sa.Column("node", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("prompt_cache_hit_tokens", sa.Integer(), nullable=False),
        sa.Column("prompt_cache_miss_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_microusd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["trace_span_id"], [f"{SCHEMA}.trace_spans.id"], ondelete="CASCADE"
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("usage_ledger", schema=SCHEMA)
    op.drop_index("ix_trace_spans_run_started", table_name="trace_spans", schema=SCHEMA)
    op.drop_table("trace_spans", schema=SCHEMA)
    op.drop_table("traces", schema=SCHEMA)
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA}"))
