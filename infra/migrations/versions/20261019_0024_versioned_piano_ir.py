"""Admit explicit music v2 only after dual readers; block incompatible rollback."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_0024"
down_revision: str | None = "20261019_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def music_check(column: str) -> str:
    return f"""(({column}->>'schema_version' = 'arrangement-ir.v1'
 AND NOT ({column} ? 'render_profile') AND NOT ({column} ? 'performance_plan')) OR
 ({column}->>'schema_version' = 'arrangement-ir.v2'
 AND {column}->'render_profile'->>'schema_version' = 'render-profile.v1'
 AND {column}->'performance_plan'->>'schema_version' = 'performance-plan.v1'
 AND {column}->'render_profile'->>'engine_version' = 'motif-forge-audio-engine.v2'
 AND versions->>'domain_schema' = 'arrangement-ir.v2'
 AND versions->>'audio_engine' = 'motif-forge-audio-engine.v2'
 AND versions->>'assets' = {column}->'render_profile'->>'manifest_sha256')) IS TRUE"""


def upgrade() -> None:
    op.create_check_constraint(
        "revision_music_version", "project_revisions", music_check("arrangement_ir"), schema="app"
    )
    op.create_check_constraint(
        "candidate_music_version", "candidate_snapshots", music_check("candidate_ir"), schema="app"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
      SELECT EXISTS (SELECT 1 FROM app.project_revisions WHERE
 arrangement_ir->>'schema_version'='arrangement-ir.v2')
      OR EXISTS (SELECT 1 FROM app.candidate_snapshots WHERE
 candidate_ir->>'schema_version'='arrangement-ir.v2')
      OR EXISTS (SELECT 1 FROM app.jobs WHERE
 input_payload->>'audio_engine_version'='motif-forge-audio-engine.v2'
          OR input_payload->'plan'->>'engine_version'='motif-forge-audio-engine.v2')
      OR EXISTS (SELECT 1 FROM app.artifacts WHERE
 rebuild_recipe->>'engine_version'='motif-forge-audio-engine.v2')
    """)
        )
        .scalar()
    ):
        raise RuntimeError("IR_V2_DOWNGRADE_BLOCKED")
    op.drop_constraint(
        op.f("ck_candidate_snapshots_candidate_music_version"),
        "candidate_snapshots",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_project_revisions_revision_music_version"),
        "project_revisions",
        schema="app",
        type_="check",
    )
