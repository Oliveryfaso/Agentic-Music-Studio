"""Version immutable CompositionPlan hashes without rewriting legacy references."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0015"
down_revision: str | None = "20260813_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "composition_plans",
        sa.Column(
            "hash_version",
            sa.String(48),
            nullable=False,
            server_default="composition-plan-hash.rounded-v1",
        ),
        schema="app",
    )
    op.create_check_constraint(
        "composition_plans_hash_version_valid",
        "composition_plans",
        "hash_version IN ('composition-plan-hash.rounded-v1', "
        "'composition-plan-hash.lossless-v2')",
        schema="app",
    )
    op.alter_column(
        "composition_plans",
        "hash_version",
        server_default="composition-plan-hash.lossless-v2",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "composition_plans_hash_version_valid",
        "composition_plans",
        schema="app",
        type_="check",
    )
    op.drop_column("composition_plans", "hash_version", schema="app")
