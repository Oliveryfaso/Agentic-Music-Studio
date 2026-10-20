"""Bind source-aware semantic record v2 without rewriting legacy results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20261020_0030"
down_revision: str | None = "20261019_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORD = """(jsonb_typeof(payload) = 'object'
 AND payload->>'schema_version' = schema_version
 AND ((schema_version = 'piano-plan-record.v1'
 AND payload->'plan'->>'schema_version' = 'accompaniment-plan.v1')
 OR (schema_version = 'piano-plan-record.v2'
 AND payload->'plan'->>'schema_version' = 'accompaniment-plan.v2'
 AND payload->'request'->>'schema_version' = 'piano-semantic-request.v2'
 AND payload->'source'->>'score_id' = payload->'request'->>'source_score_id'
 AND payload->'plan'->'beats_per_bar' = payload->'request'->'beats_per_bar'
 AND ((payload->'source' = '{
 "score_id": "c01-minuet-g-a16.v1",
 "beats_per_bar": 3,
 "measure_count": 16,
 "xml_sha256": "7f223a9cc8b64af65a28f4a12892acca6b65a7acf8391a820bfba0ff4cd3ac72"
}'::jsonb AND payload->'request'->'beats_per_bar' = '3'::jsonb)
 OR (payload->'source' = '{
 "score_id": "c02-la-candeur-a8.v1",
 "beats_per_bar": 4,
 "measure_count": 8,
 "xml_sha256": "3bbe6a5e4e1487679e87570835039ffe143092176f49b097168c54b7f9376663"
}'::jsonb AND payload->'request'->'beats_per_bar' = '4'::jsonb)
 OR (payload->'source' = '{
 "score_id": "j01-bethena-a-first8.v1",
 "beats_per_bar": 3,
 "measure_count": 8,
 "xml_sha256": "1f7116b0950708f16bfc3ef3434fc7c34c810a646715aae92f3d4ce8dc72ecc6"
}'::jsonb AND payload->'request'->'beats_per_bar' = '3'::jsonb))))) IS TRUE"""
LEGACY_RECORD = (
    "(schema_version = 'piano-plan-record.v1' AND jsonb_typeof(payload) = 'object' AND "
    "payload->>'schema_version' = schema_version) IS TRUE"
)


def change_record_check(value: str) -> None:
    op.drop_constraint(
        op.f("ck_piano_accompaniment_plans_piano_accompaniment_plans_version_valid"),
        "piano_accompaniment_plans",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "piano_accompaniment_plans_version_valid", "piano_accompaniment_plans", value, schema="app"
    )


def upgrade() -> None:
    change_record_check(RECORD)


def downgrade() -> None:
    if not context.is_offline_mode():
        blocked = op.get_bind().scalar(
            sa.text("""
SELECT EXISTS(SELECT 1 FROM app.piano_accompaniment_plans
 WHERE schema_version='piano-plan-record.v2'
 OR payload->>'schema_version'='piano-plan-record.v2')
 OR EXISTS(SELECT 1 FROM app.ai_runs
 WHERE edit_request->'piano_request'->>'schema_version'='piano-semantic-request.v2')
 OR EXISTS(SELECT 1 FROM app.project_revisions,
 jsonb_array_elements(arrangement_ir->'provenance') AS p WHERE p->>'ref' IN (
 'score:c01-minuet-g-a16.v1','score:c02-la-candeur-a8.v1','score:j01-bethena-a-first8.v1'))
 OR EXISTS(SELECT 1 FROM app.candidate_snapshots,
 jsonb_array_elements(candidate_ir->'provenance') AS p WHERE p->>'ref' IN (
 'score:c01-minuet-g-a16.v1','score:c02-la-candeur-a8.v1','score:j01-bethena-a-first8.v1'))
""")
        )
        if blocked:
            raise RuntimeError("PIANO_SEMANTIC_V2_DOWNGRADE_BLOCKED")
    change_record_check(LEGACY_RECORD)
