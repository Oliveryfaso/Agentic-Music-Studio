"""Add durable media Run/Job/Outbox/Inbox and audio Artifact metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0004"
down_revision: str | None = "20260811_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("thread_id", sa.String(160), nullable=False),
        sa.Column("run_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("waiting_for_job_id", uuid, nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        schema=SCHEMA,
    )
    op.create_index("ix_runs_project_status", "runs", ["project_id", "status"], schema=SCHEMA)
    op.create_table(
        "jobs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid, nullable=False),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("input_payload", jsonb, nullable=False),
        sa.Column("output_quality_profile", sa.String(48), nullable=False),
        sa.Column("result_artifact_id", uuid),
        sa.Column("error_code", sa.String(100)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["app.runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        sa.UniqueConstraint(
            "project_id", "job_type", "idempotency_key", name="uq_jobs_project_type_key"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_jobs_run_status", "jobs", ["run_id", "status"], schema=SCHEMA)
    op.create_table(
        "run_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid, nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["app.runs.id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_run_events_run_created", "run_events", ["run_id", "created_at"], schema=SCHEMA
    )
    op.create_table(
        "job_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("job_id", uuid, nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("external_event_id", sa.String(200)),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["app.jobs.id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_job_events_job_created", "job_events", ["job_id", "created_at"], schema=SCHEMA
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("aggregate_id", uuid, nullable=False),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("dedupe_key", sa.String(240), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_events_status_created",
        "outbox_events",
        ["status", "created_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "inbox_receipts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("consumer", sa.String(100), nullable=False),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("consumer", "event_id", name="uq_inbox_receipts_consumer_event"),
        schema=SCHEMA,
    )
    op.create_table(
        "artifacts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("source_job_id", uuid, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("media_role", sa.String(80), nullable=False),
        sa.Column("quality_profile", sa.String(48), nullable=False),
        sa.Column("container", sa.String(24), nullable=False),
        sa.Column("codec", sa.String(40), nullable=False),
        sa.Column("sample_rate_hz", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("duration_milliseconds", sa.Integer(), nullable=False),
        sa.Column("bitrate_kbps", sa.Integer()),
        sa.Column("bit_depth", sa.Integer()),
        sa.Column("encoder", sa.String(120), nullable=False),
        sa.Column("encoder_version", sa.String(80), nullable=False),
        sa.Column("lifecycle_class", sa.String(24), nullable=False),
        sa.Column("availability", sa.String(24), nullable=False),
        sa.Column("recipe_hash", sa.String(64)),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        sa.ForeignKeyConstraint(["source_job_id"], ["app.jobs.id"]),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            "quality_profile",
            name="uq_artifacts_project_hash_quality",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_artifacts_project_lifecycle",
        "artifacts",
        ["project_id", "lifecycle_class"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_artifacts_project_lifecycle", table_name="artifacts", schema=SCHEMA)
    op.drop_table("artifacts", schema=SCHEMA)
    op.drop_table("inbox_receipts", schema=SCHEMA)
    op.drop_index("ix_outbox_events_status_created", table_name="outbox_events", schema=SCHEMA)
    op.drop_table("outbox_events", schema=SCHEMA)
    op.drop_index("ix_job_events_job_created", table_name="job_events", schema=SCHEMA)
    op.drop_table("job_events", schema=SCHEMA)
    op.drop_index("ix_run_events_run_created", table_name="run_events", schema=SCHEMA)
    op.drop_table("run_events", schema=SCHEMA)
    op.drop_index("ix_jobs_run_status", table_name="jobs", schema=SCHEMA)
    op.drop_table("jobs", schema=SCHEMA)
    op.drop_index("ix_runs_project_status", table_name="runs", schema=SCHEMA)
    op.drop_table("runs", schema=SCHEMA)
