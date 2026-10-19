"""Admit piano export plan/receipt versions without broadening legacy engines."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_0025"
down_revision: str | None = "20261019_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_CHECK = """((schema_version='media-run.v1'
 AND run_type NOT IN ('complete_song_export.v2','parent.export.v1')
 AND export_plan IS NULL AND plan_hash IS NULL) OR
 (schema_version='media-run.v2' AND run_type IN ('complete_song_export.v2','parent.export.v1')
 AND export_plan IS NOT NULL AND plan_hash ~ '^[0-9a-f]{64}$'
 AND export_plan->>'project_id'=project_id::text AND
 ((export_plan->>'schema_version'='export-plan.v2' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v1') OR
  (export_plan->>'schema_version'='export-plan.v3' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v2'
   AND export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v2')))) IS TRUE"""
BUNDLE_CHECK = """((schema_version='export-bundle-artifact.v1'
 AND export_plan IS NULL AND plan_hash IS NULL) OR
 (export_plan IS NOT NULL AND plan_hash ~ '^[0-9a-f]{64}$'
  AND export_plan->>'project_id'=project_id::text AND export_plan->>'revision_id'=revision_id::text
  AND export_plan->>'arrangement_hash'=arrangement_hash AND file_count>=8
  AND export_plan->>'engine_version'=engine_version AND
  ((schema_version='export-bundle-artifact.v2' AND export_plan->>'schema_version'='export-plan.v2'
    AND engine_version='motif-forge-audio-engine.v1') OR
   (schema_version='export-bundle-artifact.v3' AND export_plan->>'schema_version'='export-plan.v3'
    AND engine_version='motif-forge-audio-engine.v2')))) IS TRUE"""


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_runs_run_versioned_export_plan"), "runs", schema="app", type_="check"
    )
    op.create_check_constraint("run_versioned_export_plan", "runs", RUN_CHECK, schema="app")
    op.drop_constraint(
        op.f("ck_export_bundle_artifacts_export_bundle_versioned_plan"),
        "export_bundle_artifacts",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "export_bundle_versioned_plan", "export_bundle_artifacts", BUNDLE_CHECK, schema="app"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
       SELECT EXISTS(SELECT 1 FROM app.runs WHERE export_plan->>'schema_version'='export-plan.v3')
       OR EXISTS(SELECT 1 FROM app.export_bundle_artifacts WHERE
 schema_version='export-bundle-artifact.v3')
       OR EXISTS(SELECT 1 FROM app.jobs WHERE input_payload->>'schema_version' IN
 ('canonical-render-job.v2','candidate-preview-job.v2'))
       OR EXISTS(SELECT 1 FROM app.artifacts WHERE
 rebuild_recipe->>'engine_version'='motif-forge-audio-engine.v2')
    """)
        )
        .scalar()
    ):
        raise RuntimeError("PIANO_EXPORT_DOWNGRADE_BLOCKED")
    # Original checks are frozen in prior migration sources, independent of runtime tables.
    old_run = """((schema_version='media-run.v1'
 AND run_type NOT IN ('complete_song_export.v2','parent.export.v1')
        AND export_plan IS NULL AND plan_hash IS NULL) OR (schema_version='media-run.v2'
        AND run_type IN ('complete_song_export.v2','parent.export.v1') AND export_plan IS NOT NULL
        AND plan_hash ~ '^[0-9a-f]{64}$' AND export_plan->>'schema_version'='export-plan.v2'
        AND export_plan->>'project_id'=project_id::text)) IS TRUE"""
    old_bundle = """((schema_version='export-bundle-artifact.v1'
 AND export_plan IS NULL AND plan_hash IS NULL) OR
        (schema_version='export-bundle-artifact.v2' AND export_plan IS NOT NULL AND plan_hash ~
 '^[0-9a-f]{64}$'
        AND export_plan->>'schema_version'='export-plan.v2' AND
 export_plan->>'project_id'=project_id::text
        AND export_plan->>'revision_id'=revision_id::text AND
 export_plan->>'arrangement_hash'=arrangement_hash
        AND file_count>=8)) IS TRUE"""
    op.drop_constraint(
        op.f("ck_export_bundle_artifacts_export_bundle_versioned_plan"),
        "export_bundle_artifacts",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "export_bundle_versioned_plan", "export_bundle_artifacts", old_bundle, schema="app"
    )
    op.drop_constraint(
        op.f("ck_runs_run_versioned_export_plan"), "runs", schema="app", type_="check"
    )
    op.create_check_constraint("run_versioned_export_plan", "runs", old_run, schema="app")
