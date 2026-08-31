"""Add authoritative CandidateSnapshot lineage to candidate preview Artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0018"
down_revision: str | None = "20260820_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _lineage_constraint() -> str:
    return """
        (quality_profile IN ('canonical-master.v1', 'canonical-stem.v1', 'delivery-mp3.v1')
         AND revision_id IS NOT NULL AND candidate_snapshot_id IS NULL
         AND arrangement_hash IS NOT NULL AND render_scope IS NOT NULL)
        OR
        (quality_profile = 'candidate-preview.v1'
         AND revision_id IS NULL AND candidate_snapshot_id IS NOT NULL
         AND arrangement_hash IS NOT NULL AND render_scope = 'master'
         AND render_track_ids = '[]'::jsonb)
        OR
        (quality_profile NOT IN (
            'canonical-master.v1', 'canonical-stem.v1',
            'delivery-mp3.v1', 'candidate-preview.v1'
         )
         AND revision_id IS NULL AND candidate_snapshot_id IS NULL
         AND arrangement_hash IS NULL AND render_scope IS NULL
         AND render_track_ids = '[]'::jsonb)
    """


def _drop_historical_lineage_constraints() -> None:
    # Some long-lived local databases were created before this check was
    # consistently named, while current Alembic naming conventions prefix it.
    # PostgreSQL's IF EXISTS keeps both upgrade histories recoverable.
    op.execute(
        "ALTER TABLE app.artifacts DROP CONSTRAINT IF EXISTS "
        "ck_artifacts_artifacts_final_revision_lineage"
    )
    op.execute(
        "ALTER TABLE app.artifacts DROP CONSTRAINT IF EXISTS "
        "artifacts_final_revision_lineage"
    )


def _backfill_historical_final_lineage() -> None:
    op.execute(
        """
        UPDATE app.artifacts AS artifact
        SET revision_id = (job.input_payload->>'revision_id')::uuid,
            arrangement_hash = job.input_payload->>'arrangement_hash',
            render_scope = job.input_payload->>'render_scope',
            render_track_ids = COALESCE(
                job.input_payload->'render_track_ids', '[]'::jsonb
            ),
            schema_version = 'audio-artifact.v2'
        FROM app.jobs AS job
        WHERE artifact.source_job_id = job.id
          AND artifact.revision_id IS NULL
          AND artifact.quality_profile IN (
              'canonical-master.v1', 'canonical-stem.v1'
          )
        """
    )
    op.execute(
        """
        UPDATE app.artifacts AS artifact
        SET revision_id = (job.input_payload->>'revision_id')::uuid,
            arrangement_hash = source.arrangement_hash,
            render_scope = 'master',
            render_track_ids = '[]'::jsonb,
            schema_version = 'audio-artifact.v2'
        FROM app.jobs AS job, app.artifacts AS source
        WHERE artifact.source_job_id = job.id
          AND artifact.revision_id IS NULL
          AND artifact.quality_profile = 'delivery-mp3.v1'
          AND source.id = (job.input_payload->>'source_artifact_id')::uuid
        """
    )


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("candidate_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="app",
    )
    op.create_foreign_key(
        "fk_artifacts_candidate_snapshot",
        "artifacts",
        "candidate_snapshots",
        ["candidate_snapshot_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
    )
    _backfill_historical_final_lineage()
    _drop_historical_lineage_constraints()
    op.create_check_constraint(
        "artifacts_final_revision_lineage",
        "artifacts",
        _lineage_constraint(),
        schema="app",
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        count = op.get_bind().scalar(
            sa.text(
                "SELECT count(*) FROM app.artifacts "
                "WHERE candidate_snapshot_id IS NOT NULL"
            )
        )
        if count:
            raise RuntimeError(
                "cannot downgrade 0018 while candidate preview Artifacts exist"
            )
    _drop_historical_lineage_constraints()
    op.create_check_constraint(
        "artifacts_final_revision_lineage",
        "artifacts",
        """
        (quality_profile IN ('canonical-master.v1', 'canonical-stem.v1', 'delivery-mp3.v1')
         AND revision_id IS NOT NULL AND arrangement_hash IS NOT NULL
         AND render_scope IS NOT NULL)
        OR
        (quality_profile NOT IN ('canonical-master.v1', 'canonical-stem.v1', 'delivery-mp3.v1')
         AND revision_id IS NULL AND arrangement_hash IS NULL AND render_scope IS NULL
         AND render_track_ids = '[]'::jsonb)
        """,
        schema="app",
    )
    op.drop_constraint(
        "fk_artifacts_candidate_snapshot", "artifacts", schema="app", type_="foreignkey"
    )
    op.drop_column("artifacts", "candidate_snapshot_id", schema="app")
