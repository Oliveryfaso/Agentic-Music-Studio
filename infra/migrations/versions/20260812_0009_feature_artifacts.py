"""Add independent rebuildable waveform and analysis Feature Artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0009"
down_revision: str | None = "20260812_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.alter_column("jobs", "output_quality_profile", nullable=True, schema=SCHEMA)
    op.add_column(
        "jobs", sa.Column("output_feature_profile", sa.String(64), nullable=True), schema=SCHEMA
    )
    op.create_check_constraint(
        "jobs_exactly_one_output_profile",
        "jobs",
        "(output_quality_profile IS NULL) <> (output_feature_profile IS NULL)",
        schema=SCHEMA,
    )
    op.create_table(
        "feature_artifacts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("source_job_id", uuid, nullable=False),
        sa.Column("source_audio_artifact_id", uuid, nullable=False),
        sa.Column("source_audio_content_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("feature_profile", sa.String(64), nullable=False),
        sa.Column("feature_schema_version", sa.String(80), nullable=False),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("lifecycle_class", sa.String(24), nullable=False),
        sa.Column("availability", sa.String(24), nullable=False),
        sa.Column("recipe_hash", sa.String(64), nullable=False),
        sa.Column("rebuild_recipe", jsonb, nullable=False),
        sa.Column("protection_reasons", jsonb, nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("evicted_at", sa.DateTime(timezone=True)),
        sa.Column("rehydration_job_id", uuid),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        sa.ForeignKeyConstraint(["source_job_id"], ["app.jobs.id"]),
        sa.ForeignKeyConstraint(["source_audio_artifact_id"], ["app.artifacts.id"]),
        sa.UniqueConstraint(
            "source_audio_artifact_id",
            "source_audio_content_hash",
            "feature_profile",
            name="uq_feature_artifacts_source_profile",
        ),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            "feature_profile",
            name="uq_feature_artifacts_project_hash_profile",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_feature_artifacts_project_lifecycle",
        "feature_artifacts",
        ["project_id", "lifecycle_class"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_feature_artifacts_availability_accessed",
        "feature_artifacts",
        ["availability", "last_accessed_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feature_artifacts_availability_accessed",
        table_name="feature_artifacts",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_feature_artifacts_project_lifecycle",
        table_name="feature_artifacts",
        schema=SCHEMA,
    )
    op.drop_table("feature_artifacts", schema=SCHEMA)
    op.drop_constraint("ck_jobs_jobs_exactly_one_output_profile", "jobs", schema=SCHEMA)
    op.drop_column("jobs", "output_feature_profile", schema=SCHEMA)
    op.alter_column("jobs", "output_quality_profile", nullable=False, schema=SCHEMA)
