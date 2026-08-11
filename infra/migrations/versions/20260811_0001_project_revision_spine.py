"""Create the project and immutable Revision persistence spine."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS app"))
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "projects",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active_branch_id", uuid, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "project_revisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("parent_id", uuid),
        sa.Column("created_on_branch_id", uuid, nullable=False),
        sa.Column("arrangement_ir", jsonb, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("command_batch_id", uuid),
        sa.Column("change_impact_predicted", sa.Integer(), nullable=False),
        sa.Column("change_impact_actual", sa.Integer(), nullable=False),
        sa.Column("author_kind", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("source_run_id", uuid),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("versions", jsonb, nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "change_impact_predicted BETWEEN 0 AND 3",
            name="revision_predicted_impact_range",
        ),
        sa.CheckConstraint(
            "change_impact_actual BETWEEN 0 AND 3",
            name="revision_actual_impact_range",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["app.project_revisions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "id", name="uq_project_revisions_project_id_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_project_revisions_project_created",
        "project_revisions",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "project_branches",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("head_revision_id", uuid, nullable=False),
        sa.Column("base_revision_id", uuid, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["base_revision_id"], ["app.project_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "head_revision_id"],
            ["app.project_revisions.project_id", "app.project_revisions.id"],
            name="fk_project_branches_head_revision_project_revisions",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint("project_id", "name", name="uq_project_branches_project_name"),
        schema=SCHEMA,
    )
    op.create_table(
        "command_batches",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("branch_id", uuid, nullable=False),
        sa.Column("base_revision_id", uuid, nullable=False),
        sa.Column("resulting_revision_id", uuid, nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("predicted_impact", sa.Integer(), nullable=False),
        sa.Column("actual_impact", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["app.project_branches.id"]),
        sa.ForeignKeyConstraint(["base_revision_id"], ["app.project_revisions.id"]),
        sa.ForeignKeyConstraint(
            ["resulting_revision_id"],
            ["app.project_revisions.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_command_batches_idempotency"),
        schema=SCHEMA,
    )
    op.create_table(
        "revision_commands",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("revision_id", uuid, nullable=False),
        sa.Column("command_batch_id", uuid, nullable=False),
        sa.Column("command_id", uuid, nullable=False),
        sa.Column("command_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("selection", jsonb, nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("client_sequence", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["app.project_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["command_batch_id"], ["app.command_batches.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("command_id", name="uq_revision_commands_command_id"),
        sa.UniqueConstraint("revision_id", "client_sequence", name="uq_revision_commands_sequence"),
        schema=SCHEMA,
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_id", uuid, nullable=False),
        sa.Column("result_payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("operation", "idempotency_key", name="uq_idempotency_operation_key"),
        schema=SCHEMA,
    )
    op.create_table(
        "audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("resource_id", uuid, nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["app.projects.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_project_created",
        "audit_events",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_foreign_key(
        "fk_projects_active_branch_id_project_branches",
        "projects",
        "project_branches",
        ["active_branch_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_project_revisions_created_on_branch_id_project_branches",
        "project_revisions",
        "project_branches",
        ["created_on_branch_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_project_revisions_command_batch_id_command_batches",
        "project_revisions",
        "command_batches",
        ["command_batch_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_project_revisions_command_batch_id_command_batches",
        "project_revisions",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_project_revisions_created_on_branch_id_project_branches",
        "project_revisions",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_projects_active_branch_id_project_branches",
        "projects",
        schema=SCHEMA,
        type_="foreignkey",
    )
    for table in (
        "audit_events",
        "idempotency_records",
        "revision_commands",
        "command_batches",
        "project_branches",
        "project_revisions",
        "projects",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.execute(sa.text("DROP SCHEMA IF EXISTS app"))
