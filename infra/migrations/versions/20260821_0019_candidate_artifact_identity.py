"""Make candidate preview Artifact identity Snapshot- and Job-specific."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260821_0019"
down_revision: str | None = "20260820_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_artifacts_project_hash_quality", "artifacts", schema="app", type_="unique"
    )
    op.create_index(
        "uq_artifacts_non_candidate_content",
        "artifacts",
        ["project_id", "content_hash", "quality_profile"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("candidate_snapshot_id IS NULL"),
    )
    op.create_index(
        "uq_artifacts_candidate_job_content",
        "artifacts",
        [
            "project_id",
            "candidate_snapshot_id",
            "source_job_id",
            "content_hash",
            "quality_profile",
        ],
        unique=True,
        schema="app",
        postgresql_where=sa.text("candidate_snapshot_id IS NOT NULL"),
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        duplicates = op.get_bind().scalar(
            sa.text(
                "SELECT count(*) FROM ("
                "SELECT project_id, content_hash, quality_profile FROM app.artifacts "
                "GROUP BY project_id, content_hash, quality_profile HAVING count(*) > 1"
                ") AS duplicate_content"
            )
        )
        if duplicates:
            raise RuntimeError(
                "cannot downgrade 0019 while candidate-specific duplicate content exists"
            )
    op.drop_index("uq_artifacts_candidate_job_content", table_name="artifacts", schema="app")
    op.drop_index("uq_artifacts_non_candidate_content", table_name="artifacts", schema="app")
    op.create_unique_constraint(
        "uq_artifacts_project_hash_quality",
        "artifacts",
        ["project_id", "content_hash", "quality_profile"],
        schema="app",
    )
