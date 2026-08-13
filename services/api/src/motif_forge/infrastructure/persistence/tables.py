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
OBSERVABILITY_SCHEMA = "observability"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=APP_SCHEMA, naming_convention=NAMING_CONVENTION)


class ObservabilityBase(DeclarativeBase):
    metadata = MetaData(schema=OBSERVABILITY_SCHEMA, naming_convention=NAMING_CONVENTION)


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


class CandidateSnapshotRow(Base):
    __tablename__ = "candidate_snapshots"
    __table_args__ = (
        UniqueConstraint("candidate_id", "id", name="uq_candidate_snapshots_candidate_id_id"),
        Index("ix_candidate_snapshots_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    base_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_revisions.id"), nullable=False
    )
    source_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    parent_candidate_snapshot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.candidate_snapshots.id")
    )
    candidate_ir: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    candidate_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    commands: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    command_batch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    materialization_command_ref: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    structural_diff: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    non_target_preservation_hash: Mapped[str | None] = mapped_column(String(64))
    versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PreviewCandidateRow(Base):
    __tablename__ = "preview_candidates"
    __table_args__ = (
        CheckConstraint("actual_change_impact BETWEEN 2 AND 3", name="preview_impact_range"),
        Index("ix_preview_candidates_project_status", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    branch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_branches.id"), nullable=False
    )
    base_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_revisions.id"), nullable=False
    )
    candidate_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.candidate_snapshots.id"), nullable=False
    )
    candidate_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    structural_diff: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    actual_change_impact: Mapped[int] = mapped_column(Integer, nullable=False)
    non_target_preservation_hash: Mapped[str | None] = mapped_column(String(64))
    preview_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    analysis_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    approved_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_revisions.id")
    )
    decision_by: Mapped[str | None] = mapped_column(String(160))
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("preview_id", name="uq_approvals_preview_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    preview_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.preview_candidates.id"), nullable=False
    )
    source_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaRunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_project_status", "project_id", "status"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(String(160), nullable=False)
    run_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    waiting_for_job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaJobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "job_type", "idempotency_key", name="uq_jobs_project_type_key"
        ),
        Index("ix_jobs_run_status", "run_id", "status"),
        CheckConstraint(
            "attempts >= 0 AND attempts <= max_attempts AND max_attempts BETWEEN 1 AND 5",
            name="jobs_attempts_within_limit",
        ),
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="jobs_progress_range"),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)", name="jobs_lease_pair"
        ),
        CheckConstraint(
            "(output_quality_profile IS NULL) <> (output_feature_profile IS NULL)",
            name="jobs_exactly_one_output_profile",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_quality_profile: Mapped[str | None] = mapped_column(String(48), nullable=True)
    output_feature_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_created", "run_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobEventRow(Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_created", "job_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
        Index("ix_outbox_events_status_created", "status", "created_at"),
        Index("ix_outbox_events_dispatchable", "status", "available_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIRunRow(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "idempotency_key", name="uq_ai_runs_project_idempotency_key"
        ),
        Index("ix_ai_runs_project_status", "project_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    branch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_branches.id"), nullable=False
    )
    base_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_revisions.id"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(String(160), nullable=False)
    graph_topology_version: Mapped[str] = mapped_column(String(80), nullable=False)
    state_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    approval_assertion_hash: Mapped[str | None] = mapped_column(String(64))
    submitted_model_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    cost_microusd: Mapped[int | None] = mapped_column(BigInteger)
    pricing_version: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIRunApprovalRow(Base):
    __tablename__ = "ai_run_approvals"
    __table_args__ = (UniqueConstraint("run_id", name="uq_ai_run_approvals_run"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.ai_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    assertion_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CompositionPlanRow(Base):
    __tablename__ = "composition_plans"
    __table_args__ = (
        UniqueConstraint("run_id", "content_hash", name="uq_composition_plans_run_hash"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.ai_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    style_pack_version: Mapped[str] = mapped_column(String(80), nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIRunEventRow(Base):
    __tablename__ = "ai_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "event_type", "dedupe_key", name="uq_ai_run_events_dedupe"),
        Index("ix_ai_run_events_run_sequence", "run_id", "sequence"),
    )
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.ai_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    phase: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelRequestReservationRow(Base):
    __tablename__ = "ai_model_request_reservations"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "request_ordinal", name="uq_ai_model_request_reservations_ordinal"
        ),
        CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name="reservation_prompt_tokens_nonnegative",
        ),
        CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="reservation_completion_tokens_nonnegative",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.ai_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    request_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_operation_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    prompt_tokens: Mapped[int | None] = mapped_column(BigInteger)
    completion_tokens: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboxReceiptRow(Base):
    __tablename__ = "inbox_receipts"
    __table_args__ = (
        UniqueConstraint("consumer", "event_id", name="uq_inbox_receipts_consumer_event"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(100), nullable=False)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AudioArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "(source_job_id IS NULL) <> (source_upload_id IS NULL)",
            name="artifacts_exactly_one_source",
        ),
        CheckConstraint(
            """
            (quality_profile IN ('canonical-master.v1', 'canonical-stem.v1', 'delivery-mp3.v1')
             AND revision_id IS NOT NULL AND arrangement_hash IS NOT NULL
             AND render_scope IS NOT NULL)
            OR
            (quality_profile NOT IN ('canonical-master.v1', 'canonical-stem.v1', 'delivery-mp3.v1')
             AND revision_id IS NULL AND arrangement_hash IS NULL AND render_scope IS NULL
             AND render_track_ids = '[]'::jsonb)
            """,
            name="artifacts_final_revision_lineage",
        ),
        UniqueConstraint(
            "project_id",
            "content_hash",
            "quality_profile",
            name="uq_artifacts_project_hash_quality",
        ),
        Index("ix_artifacts_project_lifecycle", "project_id", "lifecycle_class"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_revisions.id")
    )
    arrangement_hash: Mapped[str | None] = mapped_column(String(64))
    render_scope: Mapped[str | None] = mapped_column(String(24))
    render_track_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.jobs.id"), nullable=True
    )
    source_upload_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.upload_sessions.id"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    media_role: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_profile: Mapped[str] = mapped_column(String(48), nullable=False)
    container: Mapped[str] = mapped_column(String(24), nullable=False)
    codec: Mapped[str] = mapped_column(String(40), nullable=False)
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_milliseconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer)
    bit_depth: Mapped[int | None] = mapped_column(Integer)
    encoder: Mapped[str] = mapped_column(String(120), nullable=False)
    encoder_version: Mapped[str] = mapped_column(String(80), nullable=False)
    lifecycle_class: Mapped[str] = mapped_column(String(24), nullable=False)
    availability: Mapped[str] = mapped_column(String(24), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    recipe_hash: Mapped[str | None] = mapped_column(String(64))
    rebuild_recipe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    protection_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evicted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rehydration_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExportBundleArtifactRow(Base):
    __tablename__ = "export_bundle_artifacts"
    __table_args__ = (
        UniqueConstraint("project_id", "revision_id", name="uq_export_bundles_project_revision"),
        Index("ix_export_bundles_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    source_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.jobs.id"), nullable=False
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.project_revisions.id"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_prefix: Mapped[str] = mapped_column(String(500), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    arrangement_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    input_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    lifecycle_class: Mapped[str] = mapped_column(String(24), nullable=False)
    availability: Mapped[str] = mapped_column(String(24), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FeatureArtifactRow(Base):
    __tablename__ = "feature_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "source_audio_artifact_id",
            "source_audio_content_hash",
            "feature_profile",
            name="uq_feature_artifacts_source_profile",
        ),
        UniqueConstraint(
            "project_id",
            "content_hash",
            "feature_profile",
            name="uq_feature_artifacts_project_hash_profile",
        ),
        Index("ix_feature_artifacts_project_lifecycle", "project_id", "lifecycle_class"),
        Index("ix_feature_artifacts_availability_accessed", "availability", "last_accessed_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    source_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.jobs.id"), nullable=False
    )
    source_audio_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.artifacts.id"), nullable=False
    )
    source_audio_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    feature_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    lifecycle_class: Mapped[str] = mapped_column(String(24), nullable=False)
    availability: Mapped[str] = mapped_column(String(24), nullable=False)
    recipe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rebuild_recipe: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    protection_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evicted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rehydration_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StorageEventRow(Base):
    __tablename__ = "storage_events"
    __table_args__ = (
        UniqueConstraint("operation_id", "sequence", name="uq_storage_events_operation_sequence"),
        Index("ix_storage_events_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    operation_id: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    route: Mapped[str] = mapped_column(String(40), nullable=False)
    explanation_code: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UploadSessionRow(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_upload_sessions_project_key"),
        Index("ix_upload_sessions_project_status", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(f"{APP_SCHEMA}.projects.id"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_format: Mapped[str] = mapped_column(String(16), nullable=False)
    rights_declaration: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    part_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    received_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    next_part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    quarantine_storage_key: Mapped[str | None] = mapped_column(String(500))
    detected_format: Mapped[str | None] = mapped_column(String(16))
    source_artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadPartRow(Base):
    __tablename__ = "upload_parts"
    __table_args__ = (UniqueConstraint("upload_id", "part_number", name="uq_upload_parts_number"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    upload_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{APP_SCHEMA}.upload_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TraceRow(ObservabilityBase):
    __tablename__ = "traces"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    thread_id: Mapped[str] = mapped_column(String(160), nullable=False)
    trace_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TraceSpanRow(ObservabilityBase):
    __tablename__ = "trace_spans"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_trace_spans_operation_id"),
        Index("ix_trace_spans_run_started", "run_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{OBSERVABILITY_SCHEMA}.traces.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_id: Mapped[str] = mapped_column(String(200), nullable=False)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    node: Mapped[str] = mapped_column(String(120), nullable=False)
    span_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    schema_version: Mapped[str | None] = mapped_column(String(80))
    thinking_mode: Mapped[str | None] = mapped_column(String(16))
    safe_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class UsageLedgerRow(ObservabilityBase):
    __tablename__ = "usage_ledger"

    operation_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    trace_span_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{OBSERVABILITY_SCHEMA}.trace_spans.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    node: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_cache_hit_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_cache_miss_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_microusd: Mapped[int | None] = mapped_column(BigInteger)
    cost_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    pricing_version: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
