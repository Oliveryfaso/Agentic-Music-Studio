"""Persist plan-bound dynamic export receipts without reinterpreting legacy Bundles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261019_0022"
down_revision: str | None = "20260824_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLAN_CHECK = """(
 (schema_version = 'export-bundle-artifact.v1'
  AND export_plan IS NULL AND plan_hash IS NULL)
 OR
 (schema_version = 'export-bundle-artifact.v2'
  AND export_plan IS NOT NULL AND plan_hash IS NOT NULL
  AND plan_hash ~ '^[0-9a-f]{64}$'
  AND export_plan->>'schema_version' = 'export-plan.v2'
  AND export_plan->>'project_id' = project_id::text
  AND export_plan->>'revision_id' = revision_id::text
  AND export_plan->>'arrangement_hash' = arrangement_hash
  AND file_count >= 8)
) IS TRUE"""


RUN_PLAN_CHECK = """((schema_version = 'media-run.v1'
 AND run_type <> 'complete_song_export.v2'
 AND export_plan IS NULL AND plan_hash IS NULL) OR
 (schema_version = 'media-run.v2' AND run_type = 'complete_song_export.v2'
  AND export_plan IS NOT NULL AND plan_hash IS NOT NULL
  AND plan_hash ~ '^[0-9a-f]{64}$'
  AND export_plan->>'schema_version' = 'export-plan.v2'
  AND export_plan->>'project_id' = project_id::text)) IS TRUE"""


def upgrade() -> None:
    op.add_column("runs", sa.Column("export_plan", postgresql.JSONB(), nullable=True), schema="app")
    op.add_column("runs", sa.Column("plan_hash", sa.String(64), nullable=True), schema="app")
    op.create_check_constraint("run_versioned_export_plan", "runs", RUN_PLAN_CHECK, schema="app")
    op.add_column(
        "export_bundle_artifacts",
        sa.Column("export_plan", postgresql.JSONB(), nullable=True),
        schema="app",
    )
    op.add_column(
        "export_bundle_artifacts",
        sa.Column("plan_hash", sa.String(64), nullable=True),
        schema="app",
    )
    op.create_check_constraint(
        "export_bundle_versioned_plan", "export_bundle_artifacts", PLAN_CHECK, schema="app"
    )


def downgrade() -> None:
    # Reject before any DDL: an old reader cannot safely interpret dynamic receipts.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM app.export_bundle_artifacts "
                "WHERE schema_version <> 'export-bundle-artifact.v1') OR EXISTS "
                "(SELECT 1 FROM app.runs WHERE schema_version <> 'media-run.v1')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("EXPORT_V2_DOWNGRADE_BLOCKED")
    op.drop_constraint(
        "export_bundle_versioned_plan", "export_bundle_artifacts", schema="app", type_="check"
    )
    op.drop_column("export_bundle_artifacts", "plan_hash", schema="app")
    op.drop_column("export_bundle_artifacts", "export_plan", schema="app")

    op.drop_constraint("run_versioned_export_plan", "runs", schema="app", type_="check")
    op.drop_column("runs", "plan_hash", schema="app")
    op.drop_column("runs", "export_plan", schema="app")
