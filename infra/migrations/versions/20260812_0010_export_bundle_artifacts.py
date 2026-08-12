"""Persist immutable complete Export Bundle metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0010"
down_revision: str | None = "20260812_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "export_bundle_artifacts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("source_job_id", uuid, nullable=False),
        sa.Column("revision_id", uuid, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_prefix", sa.String(500), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("arrangement_hash", sa.String(64), nullable=False),
        sa.Column("engine_version", sa.String(80), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("input_artifact_ids", jsonb, nullable=False),
        sa.Column("lifecycle_class", sa.String(24), nullable=False),
        sa.Column("availability", sa.String(24), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        sa.ForeignKeyConstraint(["source_job_id"], ["app.jobs.id"]),
        sa.ForeignKeyConstraint(["revision_id"], ["app.project_revisions.id"]),
        sa.UniqueConstraint(
            "project_id", "revision_id", name="uq_export_bundles_project_revision"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_export_bundles_project_created",
        "export_bundle_artifacts",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_export_bundles_project_created",
        table_name="export_bundle_artifacts",
        schema=SCHEMA,
    )
    op.drop_table("export_bundle_artifacts", schema=SCHEMA)
