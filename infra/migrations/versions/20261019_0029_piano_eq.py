"""Admit explicit piano EQ IR5/Job5/Plan6 and guard immutable history on downgrade."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20261019_0029"
down_revision: str | None = "20261019_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_MUSIC = """((COLUMN_NAME->>'schema_version' = 'arrangement-ir.v1'
 AND NOT (COLUMN_NAME ? 'piano_mix')
 AND NOT (COLUMN_NAME ? 'render_profile') AND NOT (COLUMN_NAME ? 'performance_plan')) OR
 (COLUMN_NAME->>'schema_version' = 'arrangement-ir.v2' AND NOT (COLUMN_NAME ? 'piano_mix')
 AND COLUMN_NAME->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND COLUMN_NAME->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND COLUMN_NAME->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v2'
 AND versions->>'domain_schema' = 'arrangement-ir.v2'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v2'
 AND versions->>'assets' = COLUMN_NAME->'render_profile'->>'manifest_sha256') OR
 (COLUMN_NAME->>'schema_version' = 'arrangement-ir.v3' AND NOT (COLUMN_NAME ? 'piano_mix')
 AND COLUMN_NAME->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND COLUMN_NAME->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND COLUMN_NAME->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v3'
 AND versions->>'domain_schema' = 'arrangement-ir.v3'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v3'
 AND versions->>'assets' = COLUMN_NAME->'render_profile'->>'manifest_sha256') OR
 (COLUMN_NAME->>'schema_version' = 'arrangement-ir.v4'
 AND COLUMN_NAME->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND COLUMN_NAME->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND COLUMN_NAME->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v4'
 AND COLUMN_NAME->'piano_mix'->>'schema_version' = 'piano-mix.v1'
 AND jsonb_typeof(COLUMN_NAME->'piano_mix'->'tracks') = 'array'
 AND jsonb_array_length(COLUMN_NAME->'piano_mix'->'tracks') = 2
 AND versions->>'domain_schema' = 'arrangement-ir.v4'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v4'
 AND versions->>'compiler' = 'audio-graph-spec.v4'
 AND versions->>'assets' = COLUMN_NAME->'render_profile'->>'manifest_sha256')) IS TRUE"""


MUSIC = """((COLUMN_NAME->>'schema_version' = 'arrangement-ir.v1'
 AND NOT (COLUMN_NAME ? 'piano_eq')
 AND NOT (COLUMN_NAME ? 'piano_mix')
 AND NOT (COLUMN_NAME ? 'render_profile') AND NOT (COLUMN_NAME ? 'performance_plan')) OR
 (COLUMN_NAME->>'schema_version' = 'arrangement-ir.v2'
 AND NOT (COLUMN_NAME ? 'piano_eq') AND NOT (COLUMN_NAME ? 'piano_mix')
 AND COLUMN_NAME->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND COLUMN_NAME->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND COLUMN_NAME->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v2'
 AND NOT (COLUMN_NAME->'render_profile' ? 'eq_profile')
 AND versions->>'domain_schema' = 'arrangement-ir.v2'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v2'
 AND versions->>'assets' = COLUMN_NAME->'render_profile'->>'manifest_sha256') OR
 (COLUMN_NAME->>'schema_version' = 'arrangement-ir.v3'
 AND NOT (COLUMN_NAME ? 'piano_eq') AND NOT (COLUMN_NAME ? 'piano_mix')
 AND COLUMN_NAME->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND COLUMN_NAME->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND COLUMN_NAME->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v3'
 AND NOT (COLUMN_NAME->'render_profile' ? 'eq_profile')
 AND versions->>'domain_schema' = 'arrangement-ir.v3'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v3'
 AND versions->>'assets' = COLUMN_NAME->'render_profile'->>'manifest_sha256') OR
 (COLUMN_NAME->>'schema_version' = 'arrangement-ir.v4'
 AND NOT (COLUMN_NAME ? 'piano_eq')
 AND COLUMN_NAME->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND COLUMN_NAME->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND COLUMN_NAME->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v4'
 AND NOT (COLUMN_NAME->'render_profile' ? 'eq_profile')
 AND COLUMN_NAME->'piano_mix'->>'schema_version' = 'piano-mix.v1'
 AND jsonb_typeof(COLUMN_NAME->'piano_mix'->'tracks') = 'array'
 AND jsonb_array_length(COLUMN_NAME->'piano_mix'->'tracks') = 2
 AND versions->>'domain_schema' = 'arrangement-ir.v4'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v4'
 AND versions->>'compiler' = 'audio-graph-spec.v4'
 AND versions->>'assets' = COLUMN_NAME->'render_profile'->>'manifest_sha256') OR
 (COLUMN_NAME->>'schema_version' = 'arrangement-ir.v5'
 AND COLUMN_NAME->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND COLUMN_NAME->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND COLUMN_NAME->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v5'
 AND COLUMN_NAME->'render_profile'->'eq_profile' = '{
"schema_version": "three-band-eq-profile.v1",
 "profile_id": "motif-three-band-static.v1",
 "sample_rate_hz": 48000,"low_frequency_hz": 180,
 "mid_frequency_hz": 1000,"mid_q": 0.8,
 "high_frequency_hz": 6000,"shelf_slope": 1.0}'::jsonb
 AND COLUMN_NAME->'piano_mix'->>'schema_version' = 'piano-mix.v1'
 AND jsonb_typeof(COLUMN_NAME->'piano_mix'->'tracks') = 'array'
 AND jsonb_array_length(COLUMN_NAME->'piano_mix'->'tracks') = 2
 AND COLUMN_NAME->'piano_eq'->>'schema_version' = 'piano-eq-state.v1'
 AND jsonb_typeof(COLUMN_NAME->'piano_eq'->'tracks') = 'array'
 AND jsonb_array_length(COLUMN_NAME->'piano_eq'->'tracks') = 2
 AND versions->>'domain_schema' = 'arrangement-ir.v5'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v5'
 AND versions->>'compiler' = 'audio-graph-spec.v5'
 AND versions->>'assets' = COLUMN_NAME->'render_profile'->>'manifest_sha256')) IS TRUE"""


LEGACY_RUN = """((schema_version='media-run.v1'
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
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v3') OR
 (export_plan->>'schema_version'='export-plan.v5' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v4' AND
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v4')))) IS TRUE"""


RUN = """((schema_version='media-run.v1'
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
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v3') OR
 (export_plan->>'schema_version'='export-plan.v5' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v4' AND
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v4') OR
 (export_plan->>'schema_version'='export-plan.v6' AND
 export_plan->>'engine_version'='motif-forge-audio-engine.v5' AND
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v5' AND
 export_plan->'render_profile'->'eq_profile'->>'profile_id'='motif-three-band-static.v1'
 )))) IS TRUE"""


LEGACY_BUNDLE = """((schema_version='export-bundle-artifact.v1'
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
 engine_version='motif-forge-audio-engine.v3') OR
 (schema_version='export-bundle-artifact.v5' AND
 export_plan->>'schema_version'='export-plan.v5' AND
 engine_version='motif-forge-audio-engine.v4')))) IS TRUE"""


BUNDLE = """((schema_version='export-bundle-artifact.v1'
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
 engine_version='motif-forge-audio-engine.v3') OR
 (schema_version='export-bundle-artifact.v5' AND
 export_plan->>'schema_version'='export-plan.v5' AND
 engine_version='motif-forge-audio-engine.v4') OR
 (schema_version='export-bundle-artifact.v6' AND
 export_plan->>'schema_version'='export-plan.v6' AND
 engine_version='motif-forge-audio-engine.v5' AND
 export_plan->'render_profile'->>'engine_version'='motif-forge-audio-engine.v5' AND
 export_plan->'render_profile'->'eq_profile'->>'profile_id'='motif-three-band-static.v1'
 )))) IS TRUE"""


def change_checks(music: str, run: str, bundle: str) -> None:
    for table, name, column in (
        ("project_revisions", "revision_music_version", "arrangement_ir"),
        ("candidate_snapshots", "candidate_music_version", "candidate_ir"),
    ):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema="app", type_="check")
        op.create_check_constraint(name, table, music.replace("COLUMN_NAME", column), schema="app")
    for table, name, check in (
        ("runs", "run_versioned_export_plan", run),
        ("export_bundle_artifacts", "export_bundle_versioned_plan", bundle),
    ):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema="app", type_="check")
        op.create_check_constraint(name, table, check, schema="app")


def upgrade() -> None:
    change_checks(MUSIC, RUN, BUNDLE)


def downgrade() -> None:
    if not context.is_offline_mode():
        blocked = op.get_bind().scalar(
            sa.text("""
 SELECT EXISTS(SELECT 1 FROM app.project_revisions WHERE
 arrangement_ir->>'schema_version'='arrangement-ir.v5')
 OR EXISTS(SELECT 1 FROM app.candidate_snapshots WHERE
 candidate_ir->>'schema_version'='arrangement-ir.v5')
 OR EXISTS(SELECT 1 FROM app.jobs WHERE
 input_payload->>'schema_version' IN
 ('canonical-render-job.v5','candidate-preview-job.v5'))
 OR EXISTS(SELECT 1 FROM app.artifacts WHERE
 rebuild_recipe->>'engine_version'='motif-forge-audio-engine.v5')
 OR EXISTS(SELECT 1 FROM app.runs WHERE export_plan->>'schema_version'='export-plan.v6')
 OR EXISTS(SELECT 1 FROM app.export_bundle_artifacts WHERE
 schema_version='export-bundle-artifact.v6')
 OR EXISTS(SELECT 1 FROM app.revision_commands WHERE command_type='set_piano_eq')
 """)
        )
        if blocked:
            raise RuntimeError("PIANO_EQ_DOWNGRADE_BLOCKED")
    change_checks(LEGACY_MUSIC, LEGACY_RUN, LEGACY_BUNDLE)
