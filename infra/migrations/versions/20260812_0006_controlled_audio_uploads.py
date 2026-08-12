"""Add controlled upload sessions and explicit upload Artifact provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0006"
down_revision: str | None = "20260811_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "upload_sessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("declared_format", sa.String(16), nullable=False),
        sa.Column("rights_declaration", sa.String(32), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("declared_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("part_size_bytes", sa.Integer(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("next_part_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("quarantine_storage_key", sa.String(500)),
        sa.Column("detected_format", sa.String(16)),
        sa.Column("source_artifact_id", uuid),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_upload_sessions_project_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_upload_sessions_project_status",
        "upload_sessions",
        ["project_id", "status"],
        schema=SCHEMA,
    )
    op.create_table(
        "upload_parts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("upload_id", uuid, nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], ["app.upload_sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("upload_id", "part_number", name="uq_upload_parts_number"),
        schema=SCHEMA,
    )
    op.alter_column("artifacts", "source_job_id", nullable=True, schema=SCHEMA)
    op.add_column("artifacts", sa.Column("source_upload_id", uuid), schema=SCHEMA)
    op.create_foreign_key(
        "fk_artifacts_source_upload_id",
        "artifacts",
        "upload_sessions",
        ["source_upload_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_check_constraint(
        "artifacts_exactly_one_source",
        "artifacts",
        "(source_job_id IS NULL) <> (source_upload_id IS NULL)",
        schema=SCHEMA,
    )
    op.alter_column("artifacts", "sample_rate_hz", nullable=True, schema=SCHEMA)
    op.alter_column("artifacts", "channels", nullable=True, schema=SCHEMA)
    op.alter_column("artifacts", "duration_milliseconds", nullable=True, schema=SCHEMA)
    op.add_column(
        "artifacts",
        sa.Column(
            "validation_status",
            sa.String(24),
            nullable=False,
            server_default="validated",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.artifacts WHERE source_upload_id IS NOT NULL)
               OR EXISTS (SELECT 1 FROM app.upload_sessions) THEN
                RAISE EXCEPTION
                    'cannot downgrade 20260812_0006 while controlled upload data exists';
            END IF;
        END $$
        """
    )
    op.drop_column("artifacts", "validation_status", schema=SCHEMA)
    op.alter_column("artifacts", "duration_milliseconds", nullable=False, schema=SCHEMA)
    op.alter_column("artifacts", "channels", nullable=False, schema=SCHEMA)
    op.alter_column("artifacts", "sample_rate_hz", nullable=False, schema=SCHEMA)
    op.drop_constraint("artifacts_exactly_one_source", "artifacts", schema=SCHEMA)
    op.drop_constraint(
        "fk_artifacts_source_upload_id", "artifacts", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_column("artifacts", "source_upload_id", schema=SCHEMA)
    op.alter_column("artifacts", "source_job_id", nullable=False, schema=SCHEMA)
    op.drop_table("upload_parts", schema=SCHEMA)
    op.drop_index("ix_upload_sessions_project_status", table_name="upload_sessions", schema=SCHEMA)
    op.drop_table("upload_sessions", schema=SCHEMA)
