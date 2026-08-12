"""Bind final Audio Artifacts to one immutable project Revision."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0012"
down_revision: str | None = "20260812_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("artifacts", sa.Column("revision_id", uuid), schema="app")
    op.add_column("artifacts", sa.Column("arrangement_hash", sa.String(64)), schema="app")
    op.add_column("artifacts", sa.Column("render_scope", sa.String(24)), schema="app")
    op.add_column(
        "artifacts",
        sa.Column(
            "render_track_ids",
            jsonb,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="app",
    )
    op.create_foreign_key(
        "fk_artifacts_revision_id_project_revisions",
        "artifacts",
        "project_revisions",
        ["revision_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
    )
    op.execute(
        """
        UPDATE app.artifacts AS artifact
        SET revision_id = (job.input_payload->>'revision_id')::uuid,
            arrangement_hash = job.input_payload->>'arrangement_hash',
            render_scope = job.input_payload->>'render_scope',
            render_track_ids = COALESCE(job.input_payload->'render_track_ids', '[]'::jsonb)
        FROM app.jobs AS job
        WHERE artifact.source_job_id = job.id
          AND artifact.quality_profile IN ('canonical-master.v1', 'canonical-stem.v1')
        """
    )
    op.execute(
        """
        UPDATE app.artifacts AS artifact
        SET revision_id = (job.input_payload->>'revision_id')::uuid,
            arrangement_hash = source.arrangement_hash,
            render_scope = 'master',
            render_track_ids = '[]'::jsonb
        FROM app.jobs AS job, app.artifacts AS source
        WHERE artifact.source_job_id = job.id
          AND artifact.quality_profile = 'delivery-mp3.v1'
          AND source.id = (job.input_payload->>'source_artifact_id')::uuid
        """
    )
    op.create_check_constraint(
        "artifacts_final_revision_lineage",
        "artifacts",
        """
        (quality_profile IN ('canonical-master.v1', 'canonical-stem.v1', 'delivery-mp3.v1')
         AND revision_id IS NOT NULL AND arrangement_hash IS NOT NULL AND render_scope IS NOT NULL)
        OR
        (quality_profile NOT IN ('canonical-master.v1', 'canonical-stem.v1', 'delivery-mp3.v1')
         AND revision_id IS NULL AND arrangement_hash IS NULL AND render_scope IS NULL
         AND render_track_ids = '[]'::jsonb)
        """,
        schema="app",
    )
    op.execute("UPDATE app.artifacts SET schema_version = 'audio-artifact.v2'")


def downgrade() -> None:
    op.execute("UPDATE app.artifacts SET schema_version = 'audio-artifact.v1'")
    op.drop_constraint(
        "ck_artifacts_artifacts_final_revision_lineage",
        "artifacts",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        "fk_artifacts_revision_id_project_revisions",
        "artifacts",
        schema="app",
        type_="foreignkey",
    )
    op.drop_column("artifacts", "render_track_ids", schema="app")
    op.drop_column("artifacts", "render_scope", schema="app")
    op.drop_column("artifacts", "arrangement_hash", schema="app")
    op.drop_column("artifacts", "revision_id", schema="app")
