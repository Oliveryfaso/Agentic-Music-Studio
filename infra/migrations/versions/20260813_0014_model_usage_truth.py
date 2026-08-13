"""Preserve provider usage truth and immutable S2 run budgets."""
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0014"
down_revision: str | None = "20260813_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_usage_columns(table: str, *, run: bool = False) -> None:
    schema = "app"
    if run:
        op.add_column(table, sa.Column("max_model_requests", sa.Integer(), nullable=False, server_default="3"), schema=schema)
        op.add_column(table, sa.Column("max_total_tokens", sa.BigInteger(), nullable=False, server_default="12000"), schema=schema)
        op.add_column(table, sa.Column("model_usage_status", sa.String(16), nullable=False, server_default="known"), schema=schema)
    else:
        op.add_column(table, sa.Column("usage_status", sa.String(16)), schema=schema)
    op.add_column(table, sa.Column("total_tokens", sa.BigInteger()), schema=schema)
    op.add_column(table, sa.Column("prompt_cache_hit_tokens", sa.BigInteger()), schema=schema)
    op.add_column(table, sa.Column("prompt_cache_miss_tokens", sa.BigInteger()), schema=schema)
    op.add_column(table, sa.Column("reasoning_tokens", sa.BigInteger()), schema=schema)


def upgrade() -> None:
    _add_usage_columns("ai_runs", run=True)
    _add_usage_columns("ai_model_request_reservations")
    op.alter_column("ai_runs", "prompt_tokens", nullable=True, server_default="0", schema="app")
    op.alter_column("ai_runs", "completion_tokens", nullable=True, server_default="0", schema="app")
    op.execute("UPDATE app.ai_runs SET total_tokens = prompt_tokens + completion_tokens, prompt_cache_hit_tokens = CASE WHEN submitted_model_requests = 0 THEN 0 ELSE NULL END, prompt_cache_miss_tokens = CASE WHEN submitted_model_requests = 0 THEN 0 ELSE NULL END, reasoning_tokens = CASE WHEN submitted_model_requests = 0 THEN 0 ELSE NULL END, model_usage_status = CASE WHEN submitted_model_requests = 0 THEN 'known' ELSE 'partial' END")
    op.execute("UPDATE app.ai_model_request_reservations SET total_tokens = prompt_tokens + completion_tokens, usage_status = 'partial' WHERE status = 'observed'")
    op.create_check_constraint("ai_runs_max_requests_range", "ai_runs", "max_model_requests BETWEEN 1 AND 3", schema="app")
    op.create_check_constraint("ai_runs_max_tokens_range", "ai_runs", "max_total_tokens BETWEEN 1 AND 12000", schema="app")
    op.create_check_constraint("ai_runs_usage_status_valid", "ai_runs", "model_usage_status IN ('known','partial','unknown')", schema="app")
    op.create_check_constraint("ai_runs_total_tokens_nonnegative", "ai_runs", "total_tokens IS NULL OR total_tokens >= 0", schema="app")
    op.create_check_constraint("reservation_usage_status_valid", "ai_model_request_reservations", "usage_status IS NULL OR usage_status IN ('known','partial','unknown')", schema="app")
    op.create_check_constraint("reservation_total_tokens_nonnegative", "ai_model_request_reservations", "total_tokens IS NULL OR total_tokens >= 0", schema="app")
    for column in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "reasoning_tokens"):
        op.alter_column("usage_ledger", column, nullable=True, schema="observability")
    op.add_column("usage_ledger", sa.Column("usage_status", sa.String(16), nullable=False, server_default="known"), schema="observability")
    op.create_check_constraint("usage_ledger_usage_status_valid", "usage_ledger", "usage_status IN ('known','partial','unknown')", schema="observability")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE observability.usage_ledger DROP CONSTRAINT IF EXISTS "
        "usage_ledger_usage_status_valid"
    )
    op.execute(
        "ALTER TABLE observability.usage_ledger DROP CONSTRAINT IF EXISTS "
        "ck_usage_ledger_usage_ledger_usage_status_valid"
    )
    op.execute("ALTER TABLE observability.usage_ledger DROP COLUMN IF EXISTS usage_status")
    op.execute("UPDATE observability.usage_ledger SET prompt_tokens=COALESCE(prompt_tokens,0), completion_tokens=COALESCE(completion_tokens,0), total_tokens=COALESCE(total_tokens,0), prompt_cache_hit_tokens=COALESCE(prompt_cache_hit_tokens,0), prompt_cache_miss_tokens=COALESCE(prompt_cache_miss_tokens,0), reasoning_tokens=COALESCE(reasoning_tokens,0)")
    for column in ("reasoning_tokens", "prompt_cache_miss_tokens", "prompt_cache_hit_tokens", "total_tokens", "completion_tokens", "prompt_tokens"):
        op.alter_column("usage_ledger", column, nullable=False, schema="observability")
    op.drop_constraint("reservation_total_tokens_nonnegative", "ai_model_request_reservations", schema="app", type_="check")
    op.drop_constraint("reservation_usage_status_valid", "ai_model_request_reservations", schema="app", type_="check")
    op.drop_constraint("ai_runs_total_tokens_nonnegative", "ai_runs", schema="app", type_="check")
    op.drop_constraint("ai_runs_usage_status_valid", "ai_runs", schema="app", type_="check")
    op.drop_constraint("ai_runs_max_tokens_range", "ai_runs", schema="app", type_="check")
    op.drop_constraint("ai_runs_max_requests_range", "ai_runs", schema="app", type_="check")
    op.execute("UPDATE app.ai_runs SET prompt_tokens = COALESCE(prompt_tokens, 0), completion_tokens = COALESCE(completion_tokens, 0)")
    op.alter_column("ai_runs", "completion_tokens", nullable=False, server_default="0", schema="app")
    op.alter_column("ai_runs", "prompt_tokens", nullable=False, server_default="0", schema="app")
    for column in ("reasoning_tokens", "prompt_cache_miss_tokens", "prompt_cache_hit_tokens", "total_tokens", "model_usage_status", "max_total_tokens", "max_model_requests"):
        op.drop_column("ai_runs", column, schema="app")
    for column in ("reasoning_tokens", "prompt_cache_miss_tokens", "prompt_cache_hit_tokens", "total_tokens", "usage_status"):
        op.drop_column("ai_model_request_reservations", column, schema="app")
