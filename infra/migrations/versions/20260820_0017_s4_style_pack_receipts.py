"""Allow four versioned S4 Style Pack identities on materialization receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260820_0017"
down_revision: str | None = "20260813_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_S4_PACKS = (
    "style:synth-ambient:v1",
    "style:minimal-electronic:v1",
    "style:classical-chamber:v1",
    "style:jazz-harmony-improvisation:v1",
)


def upgrade() -> None:
    op.drop_constraint(
        "receipt_style_pack_supported",
        "composition_materialization_receipts",
        schema="app",
        type_="check",
    )
    values = ", ".join(repr(value) for value in ("synth-ambient.v1", *_S4_PACKS))
    op.create_check_constraint(
        "receipt_style_pack_supported",
        "composition_materialization_receipts",
        f"style_pack_version IN ({values})",
        schema="app",
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        count = op.get_bind().scalar(
            sa.text(
                "SELECT count(*) FROM app.composition_materialization_receipts "
                "WHERE style_pack_version <> 'synth-ambient.v1'"
            )
        )
        if count:
            raise RuntimeError("cannot downgrade 0017 while S4 Style Pack receipts exist")
    op.drop_constraint(
        "receipt_style_pack_supported",
        "composition_materialization_receipts",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "receipt_style_pack_supported",
        "composition_materialization_receipts",
        "style_pack_version = 'synth-ambient.v1'",
        schema="app",
    )
