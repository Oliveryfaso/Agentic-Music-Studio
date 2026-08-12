"""Storage capability inspection and the bounded pressure-gate application service."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import UUID

from motif_forge.application.ports import StorageUnitOfWorkFactory
from motif_forge.domain.media_jobs import ArtifactAvailability, ArtifactLifecycle
from motif_forge.domain.storage import (
    StorageCandidateFact,
    StorageDependencyFact,
    StoragePressureDecision,
    StoragePressureFacts,
    StorageRootHealth,
    StorageRoute,
    decide_storage_pressure,
)


@dataclass(frozen=True, slots=True)
class StorageRootSnapshot:
    health: StorageRootHealth
    identity_matches: bool
    free_bytes: int


class StorageFactsLoader(Protocol):
    async def __call__(
        self, *, project_id: UUID, dependency_artifact_ids: tuple[UUID, ...]
    ) -> tuple[
        int,
        int,
        int,
        tuple[StorageDependencyFact, ...],
        tuple[StorageCandidateFact, ...],
    ]: ...


class StorageCollector(Protocol):
    async def __call__(self, *, operation_id: str, artifact_ids: tuple[UUID, ...]) -> int: ...


class StorageEventRecorder(Protocol):
    async def __call__(self, decision: StoragePressureDecision) -> None: ...


class LocalStorageRootInspector:
    """Read-only probe of the exact configured root; it never creates a fallback."""

    def __init__(self, root: Path, *, expected_device: int | None = None) -> None:
        self._root = root
        self._expected_device = expected_device

    def __call__(self) -> StorageRootSnapshot:
        try:
            if not self._root.exists() or not self._root.is_dir() or self._root.is_symlink():
                return StorageRootSnapshot(StorageRootHealth.DISCONNECTED, False, 0)
            stat = self._root.stat()
            identity_matches = self._expected_device is None or stat.st_dev == self._expected_device
            if not identity_matches:
                return StorageRootSnapshot(StorageRootHealth.CORRUPT, False, 0)
            free_bytes = shutil.disk_usage(self._root).free
            if not _mode_has_write_bit(stat.st_mode):
                return StorageRootSnapshot(StorageRootHealth.READ_ONLY, True, free_bytes)
            return StorageRootSnapshot(StorageRootHealth.READY, True, free_bytes)
        except OSError:
            return StorageRootSnapshot(StorageRootHealth.DISCONNECTED, False, 0)


class RunStoragePressureGate:
    """Evaluate, collect at most once, and re-evaluate with the same operation ID."""

    def __init__(
        self,
        *,
        inspect_root: Callable[[], StorageRootSnapshot],
        load_facts: StorageFactsLoader,
        collector: StorageCollector,
        record_event: StorageEventRecorder,
        global_quota_bytes: int,
        project_quota_bytes: int,
        temp_quota_bytes: int,
        minimum_free_bytes: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._inspect_root = inspect_root
        self._load_facts = load_facts
        self._collector = collector
        self._record_event = record_event
        self._global_quota_bytes = global_quota_bytes
        self._project_quota_bytes = project_quota_bytes
        self._temp_quota_bytes = temp_quota_bytes
        self._minimum_free_bytes = minimum_free_bytes
        self._clock = clock

    async def __call__(
        self,
        *,
        operation_id: str,
        project_id: UUID,
        estimated_artifact_bytes: int,
        estimated_temp_bytes: int,
        dependency_artifact_ids: tuple[UUID, ...] = (),
        requires_artifact_io: bool = True,
    ) -> StoragePressureDecision:
        cleanup_attempted = False
        while True:
            root = self._inspect_root()
            (
                global_usage,
                project_usage,
                temp_usage,
                dependencies,
                candidates,
            ) = await self._load_facts(
                project_id=project_id,
                dependency_artifact_ids=dependency_artifact_ids,
            )
            decision = decide_storage_pressure(
                StoragePressureFacts(
                    operation_id=operation_id,
                    project_id=project_id,
                    root_health=root.health,
                    root_identity_matches=root.identity_matches,
                    requires_artifact_io=requires_artifact_io,
                    free_bytes=root.free_bytes,
                    minimum_free_bytes=self._minimum_free_bytes,
                    global_usage_bytes=global_usage,
                    global_quota_bytes=self._global_quota_bytes,
                    project_usage_bytes=project_usage,
                    project_quota_bytes=self._project_quota_bytes,
                    temp_usage_bytes=temp_usage,
                    temp_quota_bytes=self._temp_quota_bytes,
                    estimated_artifact_bytes=estimated_artifact_bytes,
                    estimated_temp_bytes=estimated_temp_bytes,
                    dependencies=dependencies,
                    cleanup_candidates=candidates,
                    cleanup_already_attempted=cleanup_attempted,
                    evaluated_at=self._clock(),
                )
            )
            await self._record_event(decision)
            if decision.route is not StorageRoute.GC_THEN_RETRY or cleanup_attempted:
                return decision
            await self._collector(
                operation_id=operation_id,
                artifact_ids=decision.cleanup_artifact_ids,
            )
            cleanup_attempted = True


def _mode_has_write_bit(mode: int) -> bool:
    return bool(mode & 0o222)


class PostgresStorageFactsLoader:
    def __init__(
        self, uow_factory: StorageUnitOfWorkFactory, *, temp_root: Path | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._temp_root = temp_root

    async def __call__(
        self, *, project_id: UUID, dependency_artifact_ids: tuple[UUID, ...]
    ) -> tuple[
        int,
        int,
        int,
        tuple[StorageDependencyFact, ...],
        tuple[StorageCandidateFact, ...],
    ]:
        async with self._uow_factory() as transaction:
            global_usage, project_usage, _, dependencies, candidates = (
                await transaction.load_storage_facts(
                    project_id=project_id,
                    dependency_artifact_ids=dependency_artifact_ids,
                    now=datetime.now(UTC),
                )
            )
        temp_usage = (
            _directory_file_bytes(self._temp_root) if self._temp_root is not None else 0
        )
        return global_usage, project_usage, temp_usage, dependencies, candidates


def _directory_file_bytes(root: Path) -> int:
    if not root.is_dir() or root.is_symlink():
        return 0
    total = 0
    for parent, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(parent) / name).is_symlink()
        ]
        for filename in filenames:
            path = Path(parent) / filename
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
    return total


class PersistentStorageEventRecorder:
    def __init__(self, uow_factory: StorageUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, decision: StoragePressureDecision) -> None:
        async with self._uow_factory() as transaction:
            await transaction.record_storage_decision(decision)


class LocalArtifactCollector:
    """Delete only exact locked rebuildable Artifact keys, then mark them evicted."""

    def __init__(
        self,
        uow_factory: StorageUnitOfWorkFactory,
        *,
        artifact_root: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._artifact_root = artifact_root.resolve()
        self._clock = clock

    async def __call__(self, *, operation_id: str, artifact_ids: tuple[UUID, ...]) -> int:
        reclaimed = 0
        for artifact_id in artifact_ids:
            pending: Path | None = None
            target: Path | None = None
            byte_size = 0
            evicted = False
            try:
                async with self._uow_factory() as transaction:
                    artifact = await transaction.lock_artifact_for_eviction(artifact_id)
                    if (
                        artifact is None
                        or artifact.lifecycle_class is not ArtifactLifecycle.REBUILDABLE
                        or artifact.availability is not ArtifactAvailability.AVAILABLE
                        or artifact.rebuild_recipe is None
                    ):
                        continue
                    target = (self._artifact_root / artifact.storage_key).resolve()
                    if self._artifact_root not in target.parents or target.is_symlink():
                        continue
                    if not target.is_file():
                        continue
                    trash = self._artifact_root / ".gc-pending"
                    trash.mkdir(mode=0o700, exist_ok=True)
                    if trash.is_symlink():
                        continue
                    operation_hash = sha256(operation_id.encode()).hexdigest()[:16]
                    pending = trash / f"{artifact_id}.{operation_hash}.pending"
                    if pending.exists() or pending.is_symlink():
                        continue
                    os.replace(target, pending)
                    byte_size = artifact.byte_size
                    evicted = await transaction.mark_artifact_evicted(
                        artifact_id=artifact_id,
                        operation_id=operation_id,
                        evicted_at=self._clock(),
                    )
                    if not evicted:
                        raise RuntimeError("Artifact eviction lost its availability precondition")
            except Exception:
                if (
                    pending is not None
                    and target is not None
                    and pending.is_file()
                    and not target.exists()
                ):
                    os.replace(pending, target)
                raise
            if evicted and pending is not None:
                with suppress(OSError):
                    os.unlink(pending)
                reclaimed += byte_size
        return reclaimed
