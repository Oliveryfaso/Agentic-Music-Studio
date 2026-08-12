from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from motif_forge.domain.media_jobs import ArtifactAvailability, ArtifactLifecycle
from motif_forge.domain.storage import (
    StorageCandidateFact,
    StorageDependencyFact,
    StoragePressureFacts,
    StorageRootHealth,
    StorageRoute,
    decide_storage_pressure,
)

NOW = datetime(2026, 8, 12, tzinfo=UTC)
MIB = 1024**2


def _facts(**overrides: object) -> StoragePressureFacts:
    values: dict[str, object] = {
        "operation_id": "operation-storage-1",
        "project_id": UUID(int=1),
        "root_health": StorageRootHealth.READY,
        "root_identity_matches": True,
        "free_bytes": 2_000 * MIB,
        "minimum_free_bytes": 500 * MIB,
        "global_usage_bytes": 1_000 * MIB,
        "global_quota_bytes": 10_000 * MIB,
        "project_usage_bytes": 500 * MIB,
        "project_quota_bytes": 2_000 * MIB,
        "temp_usage_bytes": 100 * MIB,
        "temp_quota_bytes": 2_000 * MIB,
        "estimated_artifact_bytes": 100 * MIB,
        "estimated_temp_bytes": 100 * MIB,
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return StoragePressureFacts.model_validate(values)


def _candidate(
    *,
    size_mib: int,
    lifecycle: ArtifactLifecycle = ArtifactLifecycle.REBUILDABLE,
    protected: bool = False,
    last_access_offset: int = 0,
    project_id: UUID | None = None,
) -> StorageCandidateFact:
    return StorageCandidateFact(
        artifact_id=uuid4(),
        project_id=project_id or UUID(int=1),
        byte_size=size_mib * MIB,
        lifecycle_class=lifecycle,
        availability=ArtifactAvailability.AVAILABLE,
        recipe_complete=lifecycle is ArtifactLifecycle.REBUILDABLE,
        rebuild_inputs_available=lifecycle is ArtifactLifecycle.REBUILDABLE,
        protection_reasons=("current-revision",) if protected else (),
        last_accessed_at=NOW + timedelta(minutes=last_access_offset),
        expires_at=NOW - timedelta(hours=1),
    )


def test_ready_capacity_proceeds_without_cleanup() -> None:
    decision = decide_storage_pressure(_facts())

    assert decision.route is StorageRoute.PROCEED
    assert decision.matched_rule_id == "STO-010"
    assert decision.cleanup_artifact_ids == ()


@pytest.mark.parametrize(
    "health",
    [StorageRootHealth.DISCONNECTED, StorageRootHealth.READ_ONLY, StorageRootHealth.CORRUPT],
)
def test_unhealthy_io_root_waits_without_fallback(health: StorageRootHealth) -> None:
    decision = decide_storage_pressure(_facts(root_health=health))

    assert decision.route is StorageRoute.WAIT_FOR_STORAGE
    assert decision.error_code == "ARTIFACT_ROOT_UNAVAILABLE"


def test_state_only_operation_can_proceed_while_external_root_is_disconnected() -> None:
    decision = decide_storage_pressure(
        _facts(root_health=StorageRootHealth.DISCONNECTED, requires_artifact_io=False)
    )

    assert decision.route is StorageRoute.PROCEED


def test_evicted_dependency_routes_to_rehydrate_and_missing_fails() -> None:
    evicted_id = uuid4()
    evicted = decide_storage_pressure(
        _facts(
            dependencies=(
                StorageDependencyFact(
                    artifact_id=evicted_id,
                    availability=ArtifactAvailability.EVICTED,
                    rehydratable=True,
                ),
            )
        )
    )
    missing = decide_storage_pressure(
        _facts(
            dependencies=(
                StorageDependencyFact(
                    artifact_id=uuid4(), availability=ArtifactAvailability.MISSING
                ),
            )
        )
    )

    assert evicted.route is StorageRoute.REHYDRATE_THEN_RESUME
    assert evicted.rehydrate_artifact_ids == (evicted_id,)
    assert missing.route is StorageRoute.FAIL
    assert missing.error_code == "ARTIFACT_MISSING"


def test_gc_selects_oldest_rebuildable_and_never_protected() -> None:
    protected = _candidate(size_mib=600, protected=True, last_access_offset=-30)
    oldest = _candidate(size_mib=300, last_access_offset=-20)
    newest = _candidate(size_mib=300, last_access_offset=-10)
    decision = decide_storage_pressure(
        _facts(
            free_bytes=650 * MIB,
            estimated_artifact_bytes=400 * MIB,
            estimated_temp_bytes=0,
            cleanup_candidates=(protected, newest, oldest),
        )
    )

    assert decision.route is StorageRoute.GC_THEN_RETRY
    assert decision.cleanup_artifact_ids == (oldest.artifact_id,)
    assert protected.artifact_id not in decision.cleanup_artifact_ids
    assert decision.protected_candidate_count == 1


def test_second_capacity_failure_waits_instead_of_looping_gc() -> None:
    decision = decide_storage_pressure(
        _facts(
            free_bytes=100 * MIB,
            estimated_artifact_bytes=400 * MIB,
            estimated_temp_bytes=0,
            cleanup_already_attempted=True,
        )
    )

    assert decision.route is StorageRoute.WAIT_FOR_STORAGE
    assert decision.matched_rule_id == "STO-040"
    assert decision.error_code == "STORAGE_QUOTA_EXCEEDED"


def test_project_quota_never_evicts_another_projects_artifact() -> None:
    foreign = _candidate(size_mib=900, project_id=UUID(int=2))
    decision = decide_storage_pressure(
        _facts(
            free_bytes=2_000 * MIB,
            project_usage_bytes=1_990 * MIB,
            estimated_artifact_bytes=100 * MIB,
            estimated_temp_bytes=0,
            cleanup_candidates=(foreign,),
        )
    )

    assert decision.route is StorageRoute.WAIT_FOR_STORAGE
    assert decision.cleanup_artifact_ids == ()


def test_cleanup_is_rejected_when_total_candidates_cannot_satisfy_all_quotas() -> None:
    decision = decide_storage_pressure(
        _facts(
            free_bytes=100 * MIB,
            estimated_artifact_bytes=900 * MIB,
            estimated_temp_bytes=0,
            project_usage_bytes=1_900 * MIB,
            cleanup_candidates=(_candidate(size_mib=500),),
        )
    )

    assert decision.route is StorageRoute.GC_THEN_RETRY
    assert len(decision.cleanup_artifact_ids) == 1
