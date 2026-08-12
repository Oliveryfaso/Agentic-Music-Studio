"""Add immutable candidates, preview lifecycle, and approval records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "candidate_snapshots",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("candidate_id", uuid, nullable=False),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("base_revision_id", uuid, nullable=False),
        sa.Column("source_run_id", uuid),
        sa.Column("parent_candidate_snapshot_id", uuid),
        sa.Column("candidate_ir", jsonb, nullable=False),
        sa.Column("candidate_content_hash", sa.String(64), nullable=False),
        sa.Column("command_batch_id", uuid),
        sa.Column("materialization_command_ref", uuid),
        sa.Column("structural_diff", jsonb, nullable=False),
        sa.Column("non_target_preservation_hash", sa.String(64)),
        sa.Column("versions", jsonb, nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_revision_id"], ["app.project_revisions.id"]),
        sa.ForeignKeyConstraint(["parent_candidate_snapshot_id"], ["app.candidate_snapshots.id"]),
        sa.UniqueConstraint("candidate_id", "id", name="uq_candidate_snapshots_candidate_id_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_candidate_snapshots_project_created",
        "candidate_snapshots",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "preview_candidates",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("branch_id", uuid, nullable=False),
        sa.Column("base_revision_id", uuid, nullable=False),
        sa.Column("candidate_snapshot_id", uuid, nullable=False),
        sa.Column("candidate_content_hash", sa.String(64), nullable=False),
        sa.Column("structural_diff", jsonb, nullable=False),
        sa.Column("actual_change_impact", sa.Integer(), nullable=False),
        sa.Column("non_target_preservation_hash", sa.String(64)),
        sa.Column("preview_artifact_ids", jsonb, nullable=False),
        sa.Column("analysis_artifact_ids", jsonb, nullable=False),
        sa.Column("evidence_refs", jsonb, nullable=False),
        sa.Column("source_run_id", uuid),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("approved_revision_id", uuid),
        sa.Column("decision_by", sa.String(160)),
        sa.Column("decision_at", sa.DateTime(timezone=True)),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("actual_change_impact BETWEEN 2 AND 3", name="preview_impact_range"),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["app.project_branches.id"]),
        sa.ForeignKeyConstraint(["base_revision_id"], ["app.project_revisions.id"]),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["app.candidate_snapshots.id"]),
        sa.ForeignKeyConstraint(["approved_revision_id"], ["app.project_revisions.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_preview_candidates_project_status",
        "preview_candidates",
        ["project_id", "status"],
        schema=SCHEMA,
    )

    op.create_table(
        "approvals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("preview_id", uuid, nullable=False),
        sa.Column("source_run_id", uuid),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preview_id"], ["app.preview_candidates.id"]),
        sa.UniqueConstraint("preview_id", name="uq_approvals_preview_id"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("approvals", schema=SCHEMA)
    op.drop_index(
        "ix_preview_candidates_project_status", table_name="preview_candidates", schema=SCHEMA
    )
    op.drop_table("preview_candidates", schema=SCHEMA)
    op.drop_index(
        "ix_candidate_snapshots_project_created",
        table_name="candidate_snapshots",
        schema=SCHEMA,
    )
    op.drop_table("candidate_snapshots", schema=SCHEMA)
