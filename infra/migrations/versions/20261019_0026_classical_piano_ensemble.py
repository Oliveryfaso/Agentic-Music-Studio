"""Admit explicit two-part piano v3 and plan/receipt v4; reject incompatible downgrade."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_0026"
down_revision: str | None = "20261019_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def old_music_check(column: str) -> str:
    return f"""(({column}->>'schema_version' = 'arrangement-ir.v1'
 AND NOT ({column} ? 'render_profile') AND NOT ({column} ? 'performance_plan')) OR
 ({column}->>'schema_version' = 'arrangement-ir.v2'
 AND {column}->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND {column}->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND {column}->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v2'
 AND versions->>'domain_schema' = 'arrangement-ir.v2'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v2'
 AND versions->>'assets' = {column}->'render_profile'->>'manifest_sha256')) IS TRUE"""


def music_check(column: str) -> str:
    previous = old_music_check(column).removesuffix(") IS TRUE")
    return (
        previous
        + f""" OR
 ({column}->>'schema_version' = 'arrangement-ir.v3'
 AND {column}->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND {column}->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND {column}->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v3'
 AND versions->>'domain_schema' = 'arrangement-ir.v3'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v3'
 AND versions->>'assets' = {column}->'render_profile'->>'manifest_sha256')) IS TRUE"""
    )


RUN_CHECK = """((schema_version='media-run.v1'
 AND run_type NOT IN ('complete_song_export.v2','parent.export.v1')
 AND export_plan IS NULL AND plan_hash IS NULL) OR
 (schema_version='media-run.v2' AND run_type IN ('complete_song_export.v2','parent.export.v1')
 AND export_plan IS NOT NULL AND plan_hash ~ '^[0-9a-f]{64}$'
 AND export_plan->>'project_id'=project_id::text AND
 ((export_plan->>'schema_version'='export-plan.v2' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v1') OR
 (export_plan->>'schema_version'='export-plan.v3' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v2' AND
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v2') OR
 (export_plan->>'schema_version'='export-plan.v4' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v3' AND
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v3')))) IS TRUE"""
BUNDLE_CHECK = """((schema_version='export-bundle-artifact.v1'
 AND export_plan IS NULL AND plan_hash IS NULL) OR
 (export_plan IS NOT NULL AND plan_hash ~ '^[0-9a-f]{64}$'
 AND export_plan->>'project_id'=project_id::text AND
 export_plan->>'revision_id'=revision_id::text AND
 export_plan->>'arrangement_hash'=arrangement_hash AND file_count>=8 AND
 export_plan->>'engine_version'=engine_version AND
 ((schema_version='export-bundle-artifact.v2' AND
 export_plan->>'schema_version'='export-plan.v2' AND
 engine_version='motif-forge-audio-engine.v1') OR
 (schema_version='export-bundle-artifact.v3' AND
 export_plan->>'schema_version'='export-plan.v3' AND
 engine_version='motif-forge-audio-engine.v2') OR
 (schema_version='export-bundle-artifact.v4' AND
 export_plan->>'schema_version'='export-plan.v4' AND
 engine_version='motif-forge-audio-engine.v3')))) IS TRUE"""
OLD_RUN_CHECK = """((schema_version='media-run.v1'
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
OLD_BUNDLE_CHECK = """((schema_version='export-bundle-artifact.v1'
 AND export_plan IS NULL AND plan_hash IS NULL) OR
 (export_plan IS NOT NULL AND plan_hash ~ '^[0-9a-f]{64}$'
  AND export_plan->>'project_id'=project_id::text AND export_plan->>'revision_id'=revision_id::text
  AND export_plan->>'arrangement_hash'=arrangement_hash AND file_count>=8
  AND export_plan->>'engine_version'=engine_version AND
  ((schema_version='export-bundle-artifact.v2' AND export_plan->>'schema_version'='export-plan.v2'
    AND engine_version='motif-forge-audio-engine.v1') OR
   (schema_version='export-bundle-artifact.v3' AND export_plan->>'schema_version'='export-plan.v3'
    AND engine_version='motif-forge-audio-engine.v2')))) IS TRUE"""


def change_checks(music, run, bundle):
    for table, name, column in (
        ("project_revisions", "revision_music_version", "arrangement_ir"),
        ("candidate_snapshots", "candidate_music_version", "candidate_ir"),
    ):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema="app", type_="check")
        op.create_check_constraint(name, table, music(column), schema="app")
    for table, name, check in (
        ("runs", "run_versioned_export_plan", run),
        ("export_bundle_artifacts", "export_bundle_versioned_plan", bundle),
    ):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema="app", type_="check")
        op.create_check_constraint(name, table, check, schema="app")


def upgrade() -> None:
    change_checks(music_check, RUN_CHECK, BUNDLE_CHECK)


def downgrade() -> None:
    blocked = (
        op.get_bind()
        .execute(
            sa.text("""
 SELECT EXISTS(SELECT 1 FROM app.project_revisions WHERE
 arrangement_ir->>'schema_version'='arrangement-ir.v3')
 OR EXISTS(SELECT 1 FROM app.candidate_snapshots WHERE
 candidate_ir->>'schema_version'='arrangement-ir.v3')
 OR EXISTS(SELECT 1 FROM app.jobs WHERE input_payload->>'schema_version' IN
 ('canonical-render-job.v3','candidate-preview-job.v3'))
 OR EXISTS(SELECT 1 FROM app.artifacts WHERE
 rebuild_recipe->>'engine_version'='motif-forge-audio-engine.v3')
 OR EXISTS(SELECT 1 FROM app.runs WHERE export_plan->>'schema_version'='export-plan.v4')
 OR EXISTS(SELECT 1 FROM app.export_bundle_artifacts WHERE
 schema_version='export-bundle-artifact.v4')
 """)
        )
        .scalar()
    )
    if blocked:
        raise RuntimeError("PIANO_ENSEMBLE_DOWNGRADE_BLOCKED")
    change_checks(old_music_check, OLD_RUN_CHECK, OLD_BUNDLE_CHECK)
