"""Keep explicit export attempts and final-audio Job provenance distinct."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_0023"
down_revision: str | None = "20261019_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_CHECK = """((schema_version = 'media-run.v1'
 AND run_type NOT IN ('complete_song_export.v2','parent.export.v1')
 AND export_plan IS NULL AND plan_hash IS NULL) OR
 (schema_version = 'media-run.v2'
 AND run_type IN ('complete_song_export.v2','parent.export.v1')
 AND export_plan IS NOT NULL AND plan_hash IS NOT NULL
 AND plan_hash ~ '^[0-9a-f]{64}$'
 AND export_plan->>'schema_version' = 'export-plan.v2'
 AND export_plan->>'project_id' = project_id::text)) IS TRUE"""


def upgrade() -> None:
    op.drop_constraint(
        "uq_export_bundles_project_revision",
        "export_bundle_artifacts",
        schema="app",
        type_="unique",
    )
    op.create_index(
        "uq_export_bundles_legacy_revision",
        "export_bundle_artifacts",
        ["project_id", "revision_id"],
        schema="app",
        unique=True,
        postgresql_where=sa.text("plan_hash IS NULL"),
    )
    op.create_index(
        "uq_export_bundles_revision_plan",
        "export_bundle_artifacts",
        ["project_id", "revision_id", "plan_hash"],
        schema="app",
        unique=True,
        postgresql_where=sa.text("plan_hash IS NOT NULL"),
    )
    op.drop_index("uq_artifacts_non_candidate_content", table_name="artifacts", schema="app")
    op.create_index(
        "uq_artifacts_non_candidate_content",
        "artifacts",
        ["project_id", "content_hash", "quality_profile"],
        schema="app",
        unique=True,
        postgresql_where=sa.text("candidate_snapshot_id IS NULL AND revision_id IS NULL"),
    )
    op.create_index(
        "uq_artifacts_final_job_content",
        "artifacts",
        ["project_id", "source_job_id", "content_hash", "quality_profile"],
        schema="app",
        unique=True,
        postgresql_where=sa.text("candidate_snapshot_id IS NULL AND revision_id IS NOT NULL"),
    )
    op.drop_constraint(
        op.f("ck_runs_run_versioned_export_plan"), "runs", schema="app", type_="check"
    )
    op.create_check_constraint("run_versioned_export_plan", "runs", RUN_CHECK, schema="app")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
      SELECT EXISTS (SELECT 1 FROM app.runs WHERE run_type='parent.export.v1')
      OR EXISTS (SELECT 1 FROM app.artifacts WHERE candidate_snapshot_id IS NULL
        GROUP BY project_id,content_hash,quality_profile HAVING count(*)>1)
      OR EXISTS (SELECT 1 FROM app.export_bundle_artifacts
        GROUP BY project_id,revision_id HAVING count(*)>1)
    """)
        )
        .scalar()
    ):
        raise RuntimeError("EXPORT_REQUEST_IDENTITY_DOWNGRADE_BLOCKED")
    op.drop_index("uq_artifacts_final_job_content", table_name="artifacts", schema="app")
    op.drop_index("uq_artifacts_non_candidate_content", table_name="artifacts", schema="app")
    op.create_index(
        "uq_artifacts_non_candidate_content",
        "artifacts",
        ["project_id", "content_hash", "quality_profile"],
        schema="app",
        unique=True,
        postgresql_where=sa.text("candidate_snapshot_id IS NULL"),
    )
    op.drop_index(
        "uq_export_bundles_revision_plan", table_name="export_bundle_artifacts", schema="app"
    )
    op.drop_index(
        "uq_export_bundles_legacy_revision", table_name="export_bundle_artifacts", schema="app"
    )
    op.create_unique_constraint(
        "uq_export_bundles_project_revision",
        "export_bundle_artifacts",
        ["project_id", "revision_id"],
        schema="app",
    )
    op.drop_constraint(
        op.f("ck_runs_run_versioned_export_plan"), "runs", schema="app", type_="check"
    )
    op.create_check_constraint(
        "run_versioned_export_plan",
        "runs",
        RUN_CHECK.replace(
            "run_type NOT IN ('complete_song_export.v2','parent.export.v1')",
            "run_type <> 'complete_song_export.v2'",
        ).replace(
            "run_type IN ('complete_song_export.v2','parent.export.v1')",
            "run_type = 'complete_song_export.v2'",
        ),
        schema="app",
    )
