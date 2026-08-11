"""SQLAlchemy table mappings for the append-only project history spine."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

APP_SCHEMA = "app"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=APP_SCHEMA, naming_convention=NAMING_CONVENTION)


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active_branch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{APP_SCHEMA}.project_branches.id",
            name="fk_projects_active_branch_id_project_branches",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RevisionRow(Base):
    __tablename__ = "project_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_project_revisions_project_id_id"),
        CheckConstraint(
            "change_impact_predicted BETWEEN 0 AND 3",
            name="revision_predicted_impact_range",
        ),
        CheckConstraint(
            "change_impact_actual BETWEEN 0 AND 3",
            name="revision_actual_impact_range",
        ),
        Index("ix_project_revisions_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.project_revisions.id", ondelete="RESTRICT"),
    )
    created_on_branch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{APP_SCHEMA}.project_branches.id",
            name="fk_project_revisions_created_on_branch_id_project_branches",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    arrangement_ir: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    command_batch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{APP_SCHEMA}.command_batches.id",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    change_impact_predicted: Mapped[int] = mapped_column(Integer, nullable=False)
    change_impact_actual: Mapped[int] = mapped_column(Integer, nullable=False)
    author_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    source_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BranchRow(Base):
    __tablename__ = "project_branches"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_branches_project_name"),
        ForeignKeyConstraint(
            ["project_id", "head_revision_id"],
            [f"{APP_SCHEMA}.project_revisions.project_id", f"{APP_SCHEMA}.project_revisions.id"],
            name="fk_project_branches_head_revision_project_revisions",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    head_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    base_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.project_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)


class CommandBatchRow(Base):
    __tablename__ = "command_batches"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_command_batches_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_branches.id"), nullable=False
    )
    base_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_revisions.id"), nullable=False
    )
    resulting_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{APP_SCHEMA}.project_revisions.id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    predicted_impact: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_impact: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RevisionCommandRow(Base):
    __tablename__ = "revision_commands"
    __table_args__ = (
        UniqueConstraint("command_id", name="uq_revision_commands_command_id"),
        UniqueConstraint("revision_id", "client_sequence", name="uq_revision_commands_sequence"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.project_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    command_batch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.command_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    command_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    client_sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("operation", "idempotency_key", name="uq_idempotency_operation_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_project_created", "project_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
