"""Deterministic storage-pressure policy; the model never participates."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import ArtifactAvailability, ArtifactLifecycle

STORAGE_PRESSURE_POLICY_VERSION: Literal["storage-pressure-policy.v1"] = (
    "storage-pressure-policy.v1"
)


class StorageRootHealth(StrEnum):
    READY = "ready"
    DISCONNECTED = "disconnected"
    READ_ONLY = "read_only"
    CORRUPT = "corrupt"


class StorageScope(StrEnum):
    ARTIFACT = "artifact"
    TEMP = "temp"


class StorageRoute(StrEnum):
    PROCEED = "proceed"
    GC_THEN_RETRY = "gc_then_retry"
    REHYDRATE_THEN_RESUME = "rehydrate_then_resume"
    WAIT_FOR_STORAGE = "wait_for_storage"
    FAIL = "fail"


class StorageDependencyFact(DomainModel):
    artifact_id: UUID
    availability: ArtifactAvailability
    rehydratable: bool = False


class StorageCandidateFact(DomainModel):
    artifact_id: UUID
    project_id: UUID
    byte_size: int = Field(gt=0)
    scope: StorageScope = StorageScope.ARTIFACT
    lifecycle_class: ArtifactLifecycle
    availability: ArtifactAvailability
    recipe_complete: bool = False
    rebuild_inputs_available: bool = False
    protection_reasons: tuple[str, ...] = ()
    active_job_lease: bool = False
    last_accessed_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_times(self) -> StorageCandidateFact:
        for field_name in ("last_accessed_at", "expires_at"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        return self


class StoragePressureFacts(DomainModel):
    operation_id: str = Field(min_length=8, max_length=200)
    project_id: UUID
    root_health: StorageRootHealth
    root_identity_matches: bool
    requires_artifact_io: bool = True
    free_bytes: int = Field(ge=0)
    minimum_free_bytes: int = Field(ge=0)
    global_usage_bytes: int = Field(ge=0)
    global_quota_bytes: int = Field(gt=0)
    project_usage_bytes: int = Field(ge=0)
    project_quota_bytes: int = Field(gt=0)
    temp_usage_bytes: int = Field(ge=0)
    temp_quota_bytes: int = Field(gt=0)
    estimated_artifact_bytes: int = Field(ge=0)
    estimated_temp_bytes: int = Field(ge=0)
    dependencies: tuple[StorageDependencyFact, ...] = ()
    cleanup_candidates: tuple[StorageCandidateFact, ...] = ()
    cleanup_already_attempted: bool = False
    cancelled: bool = False
    deadline_exceeded: bool = False
    evaluated_at: datetime

    @model_validator(mode="after")
    def validate_facts(self) -> StoragePressureFacts:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return self


class StoragePressureDecision(DomainModel):
    schema_version: Literal["storage-pressure-decision.v1"] = "storage-pressure-decision.v1"
    policy_version: Literal["storage-pressure-policy.v1"] = STORAGE_PRESSURE_POLICY_VERSION
    operation_id: str
    project_id: UUID
    route: StorageRoute
    matched_rule_id: str
    explanation_code: str
    error_code: str | None = None
    cleanup_artifact_ids: tuple[UUID, ...] = ()
    rehydrate_artifact_ids: tuple[UUID, ...] = ()
    required_reclaim_bytes: int = Field(default=0, ge=0)
    planned_reclaim_bytes: int = Field(default=0, ge=0)
    protected_candidate_count: int = Field(default=0, ge=0)


def decide_storage_pressure(facts: StoragePressureFacts) -> StoragePressureDecision:
    """Apply ordered STO rules and return one stable Graph route."""

    if facts.cancelled or facts.deadline_exceeded:
        return _decision(
            facts,
            route=StorageRoute.FAIL,
            rule="STO-050",
            explanation="STORAGE_OPERATION_CANCELLED_OR_EXPIRED",
        )
    if facts.requires_artifact_io and (
        facts.root_health is not StorageRootHealth.READY or not facts.root_identity_matches
    ):
        return _decision(
            facts,
            route=StorageRoute.WAIT_FOR_STORAGE,
            rule="STO-001",
            explanation="STORAGE_ROOT_NOT_READY",
            error="ARTIFACT_ROOT_UNAVAILABLE",
        )
    missing = tuple(
        item.artifact_id
        for item in facts.dependencies
        if item.availability is ArtifactAvailability.MISSING
    )
    unrecoverable_evicted = tuple(
        item.artifact_id
        for item in facts.dependencies
        if item.availability is ArtifactAvailability.EVICTED and not item.rehydratable
    )
    if missing or unrecoverable_evicted:
        return _decision(
            facts,
            route=StorageRoute.FAIL,
            rule="STO-005",
            explanation="STORAGE_DEPENDENCY_UNRECOVERABLE",
            error=("ARTIFACT_MISSING" if missing else "ARTIFACT_REHYDRATION_FAILED"),
        )
    awaiting = tuple(
        item.artifact_id
        for item in facts.dependencies
        if item.availability in {ArtifactAvailability.EVICTED, ArtifactAvailability.REHYDRATING}
    )
    if awaiting:
        return _decision(
            facts,
            route=StorageRoute.REHYDRATE_THEN_RESUME,
            rule="STO-008",
            explanation="STORAGE_DEPENDENCY_REHYDRATION_REQUIRED",
            error=(
                "ARTIFACT_REHYDRATING"
                if any(
                    item.availability is ArtifactAvailability.REHYDRATING
                    for item in facts.dependencies
                    if item.artifact_id in awaiting
                )
                else "ARTIFACT_EVICTED"
            ),
            rehydrate=awaiting,
        )

    required = _required_reclaim(facts)
    if required == 0:
        return _decision(
            facts,
            route=StorageRoute.PROCEED,
            rule="STO-010",
            explanation="STORAGE_CAPACITY_AVAILABLE",
        )
    if facts.cleanup_already_attempted:
        return _decision(
            facts,
            route=StorageRoute.WAIT_FOR_STORAGE,
            rule="STO-040",
            explanation="STORAGE_CAPACITY_STILL_INSUFFICIENT",
            error="STORAGE_QUOTA_EXCEEDED",
            required=required,
        )

    eligible, protected_count = _eligible_candidates(facts)
    selected = _select_candidates(facts, eligible)
    if selected:
        planned = sum(item.byte_size for item in selected)
        return _decision(
            facts,
            route=StorageRoute.GC_THEN_RETRY,
            rule="STO-020",
            explanation="STORAGE_SAFE_COLLECTION_AVAILABLE",
            cleanup=tuple(item.artifact_id for item in selected),
            required=required,
            planned=planned,
            protected_count=protected_count,
        )
    if eligible:
        planned = sum(item.byte_size for item in eligible)
        return _decision(
            facts,
            route=StorageRoute.GC_THEN_RETRY,
            rule="STO-020",
            explanation="STORAGE_PARTIAL_SAFE_COLLECTION_AVAILABLE",
            cleanup=tuple(item.artifact_id for item in eligible),
            required=required,
            planned=planned,
            protected_count=protected_count,
        )
    return _decision(
        facts,
        route=StorageRoute.WAIT_FOR_STORAGE,
        rule="STO-040",
        explanation="STORAGE_ONLY_PROTECTED_OR_INSUFFICIENT_CANDIDATES",
        error="STORAGE_QUOTA_EXCEEDED",
        required=required,
        protected_count=protected_count,
    )


def _required_reclaim(facts: StoragePressureFacts) -> int:
    total_output = facts.estimated_artifact_bytes + facts.estimated_temp_bytes
    return max(
        0,
        facts.minimum_free_bytes + total_output - facts.free_bytes,
        facts.global_usage_bytes + facts.estimated_artifact_bytes - facts.global_quota_bytes,
        facts.project_usage_bytes + facts.estimated_artifact_bytes - facts.project_quota_bytes,
        facts.temp_usage_bytes + facts.estimated_temp_bytes - facts.temp_quota_bytes,
    )


def _eligible_candidates(
    facts: StoragePressureFacts,
) -> tuple[tuple[StorageCandidateFact, ...], int]:
    eligible: list[StorageCandidateFact] = []
    protected_count = 0
    for item in facts.cleanup_candidates:
        blocked = bool(item.protection_reasons) or item.active_job_lease
        if blocked:
            protected_count += 1
            continue
        if item.availability is not ArtifactAvailability.AVAILABLE:
            continue
        if item.lifecycle_class is ArtifactLifecycle.EPHEMERAL:
            if item.expires_at is not None and item.expires_at <= facts.evaluated_at:
                eligible.append(item)
            continue
        if (
            item.lifecycle_class is ArtifactLifecycle.REBUILDABLE
            and item.recipe_complete
            and item.rebuild_inputs_available
        ):
            eligible.append(item)
    eligible.sort(
        key=lambda item: (
            0 if item.lifecycle_class is ArtifactLifecycle.EPHEMERAL else 1,
            item.last_accessed_at,
            str(item.artifact_id),
        )
    )
    return tuple(eligible), protected_count


def _select_candidates(
    facts: StoragePressureFacts, eligible: tuple[StorageCandidateFact, ...]
) -> tuple[StorageCandidateFact, ...]:
    selected: list[StorageCandidateFact] = []
    root_reclaimed = artifact_reclaimed = project_reclaimed = temp_reclaimed = 0
    total_output = facts.estimated_artifact_bytes + facts.estimated_temp_bytes

    def enough() -> bool:
        return (
            facts.free_bytes + root_reclaimed - total_output >= facts.minimum_free_bytes
            and facts.global_usage_bytes + facts.estimated_artifact_bytes - artifact_reclaimed
            <= facts.global_quota_bytes
            and facts.project_usage_bytes + facts.estimated_artifact_bytes - project_reclaimed
            <= facts.project_quota_bytes
            and facts.temp_usage_bytes + facts.estimated_temp_bytes - temp_reclaimed
            <= facts.temp_quota_bytes
        )

    for item in eligible:
        if enough():
            break
        selected.append(item)
        root_reclaimed += item.byte_size
        if item.scope is StorageScope.TEMP:
            temp_reclaimed += item.byte_size
        else:
            artifact_reclaimed += item.byte_size
            if item.project_id == facts.project_id:
                project_reclaimed += item.byte_size
    return tuple(selected) if enough() else ()


def _decision(
    facts: StoragePressureFacts,
    *,
    route: StorageRoute,
    rule: str,
    explanation: str,
    error: str | None = None,
    cleanup: tuple[UUID, ...] = (),
    rehydrate: tuple[UUID, ...] = (),
    required: int = 0,
    planned: int = 0,
    protected_count: int = 0,
) -> StoragePressureDecision:
    return StoragePressureDecision(
        operation_id=facts.operation_id,
        project_id=facts.project_id,
        route=route,
        matched_rule_id=rule,
        explanation_code=explanation,
        error_code=error,
        cleanup_artifact_ids=cleanup,
        rehydrate_artifact_ids=rehydrate,
        required_reclaim_bytes=required,
        planned_reclaim_bytes=planned,
        protected_candidate_count=protected_count,
    )
