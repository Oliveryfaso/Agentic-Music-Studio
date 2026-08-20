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
    op.drop_constraint(
        "artifacts_final_revision_lineage", "artifacts", schema="app", type_="check"
    )
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
    op.drop_constraint(
        "artifacts_final_revision_lineage", "artifacts", schema="app", type_="check"
    )
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
