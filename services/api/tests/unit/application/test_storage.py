from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from motif_forge.application.storage import (
    LocalStorageRootInspector,
    RunStoragePressureGate,
    StorageRootSnapshot,
    _directory_file_bytes,
)
from motif_forge.domain.media_jobs import ArtifactAvailability, ArtifactLifecycle
from motif_forge.domain.storage import (
    StorageCandidateFact,
    StoragePressureDecision,
    StorageRootHealth,
    StorageRoute,
)


def test_temp_usage_counts_regular_files_without_following_symlinks(tmp_path: Path) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    (temp_root / "one.partial").write_bytes(b"1234")
    nested = temp_root / "nested"
    nested.mkdir()
    (nested / "two.partial").write_bytes(b"12")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "large").write_bytes(b"x" * 100)
    (temp_root / "linked").symlink_to(outside, target_is_directory=True)

    assert _directory_file_bytes(temp_root) == 6

NOW = datetime(2026, 8, 12, tzinfo=UTC)
MIB = 1024**2


class MutableFacts:
    def __init__(self) -> None:
        self.usage = 1_900 * MIB
        self.candidate = StorageCandidateFact(
            artifact_id=UUID(int=3),
            project_id=UUID(int=1),
            byte_size=500 * MIB,
            lifecycle_class=ArtifactLifecycle.REBUILDABLE,
            availability=ArtifactAvailability.AVAILABLE,
            recipe_complete=True,
            rebuild_inputs_available=True,
            last_accessed_at=NOW,
        )

    async def __call__(
        self, *, project_id: UUID, dependency_artifact_ids: tuple[UUID, ...]
    ) -> tuple[object, ...]:
        del project_id, dependency_artifact_ids
        candidates = (self.candidate,) if self.usage > 1_500 * MIB else ()
        return self.usage, self.usage, 0, (), candidates


class Collector:
    def __init__(self, facts: MutableFacts) -> None:
        self.facts = facts
        self.calls: list[tuple[str, tuple[UUID, ...]]] = []

    async def __call__(self, *, operation_id: str, artifact_ids: tuple[UUID, ...]) -> int:
        self.calls.append((operation_id, artifact_ids))
        self.facts.usage -= 500 * MIB
        return 500 * MIB


class Events:
    def __init__(self) -> None:
        self.decisions: list[StoragePressureDecision] = []

    async def __call__(self, decision: StoragePressureDecision) -> None:
        self.decisions.append(decision)


@pytest.mark.asyncio
async def test_gate_collects_once_then_proceeds_with_same_operation_id() -> None:
    facts = MutableFacts()
    collector = Collector(facts)
    events = Events()
    gate = RunStoragePressureGate(
        inspect_root=lambda: StorageRootSnapshot(StorageRootHealth.READY, True, 5_000 * MIB),
        load_facts=facts,  # type: ignore[arg-type]
        collector=collector,
        record_event=events,
        global_quota_bytes=10_000 * MIB,
        project_quota_bytes=2_000 * MIB,
        temp_quota_bytes=2_000 * MIB,
        minimum_free_bytes=500 * MIB,
        clock=lambda: NOW,
    )

    decision = await gate(
        operation_id="storage-operation-1",
        project_id=UUID(int=1),
        estimated_artifact_bytes=400 * MIB,
        estimated_temp_bytes=0,
    )

    assert decision.route is StorageRoute.PROCEED
    assert len(collector.calls) == 1
    assert [item.route for item in events.decisions] == [
        StorageRoute.GC_THEN_RETRY,
        StorageRoute.PROCEED,
    ]
    assert {item.operation_id for item in events.decisions} == {"storage-operation-1"}


def test_root_inspector_does_not_create_a_missing_external_root(tmp_path: Path) -> None:
    root = tmp_path / "disconnected-volume" / "artifacts"

    result = LocalStorageRootInspector(root)()

    assert result.health is StorageRootHealth.DISCONNECTED
    assert not root.exists()
