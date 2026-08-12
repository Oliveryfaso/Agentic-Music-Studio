"""Immutable project history, branch, candidate, and preview value objects."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.ir import ArrangementIR, DomainModel, create_empty_arrangement

REVISION_SCHEMA_VERSION = "revision.v1"
CANDIDATE_SCHEMA_VERSION = "candidate-snapshot.v1"
PREVIEW_SCHEMA_VERSION = "preview-candidate.v1"
BRANCH_SCHEMA_VERSION = "project-branch.v1"


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class ChangeImpact(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3


class AuthorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class PreviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class VersionRefs(DomainModel):
    domain_schema: str = "arrangement-ir.v1"
    policy: str = "change-impact.v1"
    audio_engine: str = "audio-engine.v1"
    graph: str | None = None
    prompt: str | None = None
    knowledge: str | None = None
    assets: str | None = None


class StructuralDiffEntry(DomainModel):
    operation: Literal["add", "remove", "replace", "move"]
    path: str = Field(min_length=1, max_length=400)
    summary: str = Field(min_length=1, max_length=400)


class Revision(DomainModel):
    schema_version: Literal["revision.v1"] = "revision.v1"
    revision_id: UUID
    project_id: UUID
    parent_revision_id: UUID | None
    created_on_branch_id: UUID
    arrangement_ir: ArrangementIR
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    command_batch_id: UUID | None = None
    change_impact_predicted: ChangeImpact
    change_impact_actual: ChangeImpact
    author_kind: AuthorKind
    created_by: str = Field(min_length=1, max_length=160)
    source_run_id: UUID | None = None
    reason_code: str = Field(min_length=1, max_length=100)
    versions: VersionRefs = Field(default_factory=VersionRefs)
    created_at: datetime

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        _require_aware(self.created_at, "created_at")
        if self.arrangement_ir.project_id != self.project_id:
            raise ValueError("revision arrangement must belong to the same project")
        if arrangement_content_hash(self.arrangement_ir) != self.content_hash:
            raise ValueError("revision content_hash does not match arrangement_ir")
        if self.parent_revision_id is None:
            if self.reason_code != "ROOT_CREATED":
                raise ValueError("only ROOT_CREATED revisions may omit parent_revision_id")
            if self.command_batch_id is not None:
                raise ValueError("root revision cannot reference a command batch")
        elif self.reason_code == "ROOT_CREATED":
            raise ValueError("ROOT_CREATED revision cannot have a parent")
        if self.change_impact_actual < self.change_impact_predicted:
            raise ValueError("actual change impact cannot be lower than predicted impact")
        return self


class ProjectBranch(DomainModel):
    schema_version: Literal["project-branch.v1"] = "project-branch.v1"
    branch_id: UUID
    project_id: UUID
    name: str = Field(min_length=1, max_length=80)
    head_revision_id: UUID
    created_from_revision_id: UUID
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_branch(self) -> Self:
        _require_aware(self.created_at, "created_at")
        return self


class CandidateSnapshot(DomainModel):
    schema_version: Literal["candidate-snapshot.v1"] = "candidate-snapshot.v1"
    candidate_snapshot_id: UUID
    candidate_id: UUID
    project_id: UUID
    base_revision_id: UUID
    source_run_id: UUID | None = None
    parent_candidate_snapshot_id: UUID | None = None
    candidate_ir: ArrangementIR
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    command_batch_id: UUID | None = None
    materialization_command_ref: UUID | None = None
    structural_diff: tuple[StructuralDiffEntry, ...] = ()
    non_target_preservation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    versions: VersionRefs = Field(default_factory=VersionRefs)
    created_at: datetime

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        _require_aware(self.created_at, "created_at")
        if self.candidate_ir.project_id != self.project_id:
            raise ValueError("candidate arrangement must belong to the same project")
        if arrangement_content_hash(self.candidate_ir) != self.candidate_content_hash:
            raise ValueError("candidate_content_hash does not match candidate_ir")
        if self.command_batch_id is not None and self.materialization_command_ref is not None:
            raise ValueError("candidate may use a command batch or materialization ref, not both")
        return self


class PreviewCandidate(DomainModel):
    schema_version: Literal["preview-candidate.v1"] = "preview-candidate.v1"
    preview_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    candidate_snapshot_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    structural_diff: tuple[StructuralDiffEntry, ...] = ()
    actual_change_impact: ChangeImpact
    non_target_preservation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    preview_artifact_ids: tuple[UUID, ...] = ()
    analysis_artifact_ids: tuple[UUID, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_run_id: UUID | None = None
    status: PreviewStatus = PreviewStatus.PENDING
    approved_revision_id: UUID | None = None
    decision_by: str | None = Field(default=None, min_length=1, max_length=160)
    decision_at: datetime | None = None
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_preview(self) -> Self:
        _require_aware(self.created_at, "created_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        terminal = self.status is not PreviewStatus.PENDING
        if terminal != (self.decision_at is not None and self.decision_by is not None):
            raise ValueError("terminal preview status requires complete decision metadata")
        if self.decision_at is not None:
            _require_aware(self.decision_at, "decision_at")
            if self.decision_at < self.created_at:
                raise ValueError("decision_at cannot predate preview creation")
        if self.status is PreviewStatus.APPROVED:
            if self.approved_revision_id is None:
                raise ValueError("approved preview must reference its new revision")
        elif self.approved_revision_id is not None:
            raise ValueError("only approved previews may reference an approved revision")
        return self


class ProjectRootState(DomainModel):
    project_id: UUID
    active_branch_id: UUID
    branch: ProjectBranch
    revision: Revision

    @model_validator(mode="after")
    def validate_root_state(self) -> Self:
        if self.branch.project_id != self.project_id or self.revision.project_id != self.project_id:
            raise ValueError("root branch and revision must belong to the project")
        if self.active_branch_id != self.branch.branch_id:
            raise ValueError("root branch must be active")
        if self.branch.head_revision_id != self.revision.revision_id:
            raise ValueError("root branch head must point to root revision")
        if self.branch.created_from_revision_id != self.revision.revision_id:
            raise ValueError("root branch must be created from root revision")
        if self.revision.created_on_branch_id != self.branch.branch_id:
            raise ValueError("root revision must record the root branch")
        return self


def create_root_state(
    project_id: UUID,
    *,
    created_by: str,
    branch_id: UUID | None = None,
    revision_id: UUID | None = None,
    created_at: datetime | None = None,
) -> ProjectRootState:
    """Create the empty root Revision and main Branch as one consistent value."""

    root_branch_id = branch_id or uuid4()
    root_revision_id = revision_id or uuid4()
    timestamp = created_at or datetime.now(UTC)
    arrangement = create_empty_arrangement(project_id)
    revision = Revision(
        revision_id=root_revision_id,
        project_id=project_id,
        parent_revision_id=None,
        created_on_branch_id=root_branch_id,
        arrangement_ir=arrangement,
        content_hash=arrangement_content_hash(arrangement),
        change_impact_predicted=ChangeImpact.L0,
        change_impact_actual=ChangeImpact.L0,
        author_kind=AuthorKind.SYSTEM,
        created_by=created_by,
        reason_code="ROOT_CREATED",
        created_at=timestamp,
    )
    branch = ProjectBranch(
        branch_id=root_branch_id,
        project_id=project_id,
        name="main",
        head_revision_id=root_revision_id,
        created_from_revision_id=root_revision_id,
        created_at=timestamp,
        created_by=created_by,
    )
    return ProjectRootState(
        project_id=project_id,
        active_branch_id=root_branch_id,
        branch=branch,
        revision=revision,
    )


def create_candidate_snapshot(
    *,
    base_revision: Revision,
    candidate_ir: ArrangementIR,
    candidate_id: UUID,
    created_at: datetime,
    candidate_snapshot_id: UUID | None = None,
    source_run_id: UUID | None = None,
    parent_candidate_snapshot_id: UUID | None = None,
    structural_diff: tuple[StructuralDiffEntry, ...] = (),
    versions: VersionRefs | None = None,
) -> CandidateSnapshot:
    """Build a hash-bound candidate against an immutable base Revision."""

    if candidate_ir.project_id != base_revision.project_id:
        raise ValueError("candidate and base revision must belong to the same project")
    return CandidateSnapshot(
        candidate_snapshot_id=candidate_snapshot_id or uuid4(),
        candidate_id=candidate_id,
        project_id=base_revision.project_id,
        base_revision_id=base_revision.revision_id,
        source_run_id=source_run_id,
        parent_candidate_snapshot_id=parent_candidate_snapshot_id,
        candidate_ir=candidate_ir,
        candidate_content_hash=arrangement_content_hash(candidate_ir),
        structural_diff=structural_diff,
        versions=versions or VersionRefs(),
        created_at=created_at,
    )


def create_preview_candidate(
    *,
    snapshot: CandidateSnapshot,
    branch: ProjectBranch,
    actual_change_impact: ChangeImpact,
    created_at: datetime,
    expires_at: datetime,
    preview_id: UUID | None = None,
) -> PreviewCandidate:
    """Create a pending preview while enforcing branch/base/snapshot identity."""

    if branch.project_id != snapshot.project_id:
        raise ValueError("preview branch and snapshot must belong to the same project")
    if branch.head_revision_id != snapshot.base_revision_id:
        raise ValueError("preview snapshot base must equal branch head")
    if actual_change_impact < ChangeImpact.L2:
        raise ValueError("L0/L1 changes commit directly and must not create previews")
    return PreviewCandidate(
        preview_id=preview_id or uuid4(),
        project_id=snapshot.project_id,
        branch_id=branch.branch_id,
        base_revision_id=snapshot.base_revision_id,
        candidate_snapshot_id=snapshot.candidate_snapshot_id,
        candidate_content_hash=snapshot.candidate_content_hash,
        structural_diff=snapshot.structural_diff,
        actual_change_impact=actual_change_impact,
        non_target_preservation_hash=snapshot.non_target_preservation_hash,
        source_run_id=snapshot.source_run_id,
        created_at=created_at,
        expires_at=expires_at,
    )


def resolve_preview_candidate(
    preview: PreviewCandidate,
    *,
    status: PreviewStatus,
    decided_by: str,
    decided_at: datetime,
    approved_revision_id: UUID | None = None,
) -> PreviewCandidate:
    """Return one terminal lifecycle update without mutating candidate content."""

    if preview.status is not PreviewStatus.PENDING:
        raise ValueError("only pending previews can be resolved")
    if status is PreviewStatus.PENDING:
        raise ValueError("preview resolution requires a terminal status")
    return PreviewCandidate.model_validate(
        {
            **preview.model_dump(),
            "status": status,
            "approved_revision_id": approved_revision_id,
            "decision_by": decided_by,
            "decision_at": decided_at,
        },
        strict=True,
    )
