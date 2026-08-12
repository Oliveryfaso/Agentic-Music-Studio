"""PostgreSQL facts, events, and exact Artifact eviction transactions."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import String, case, cast, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
    FeatureArtifact,
    JobStatus,
)
from motif_forge.domain.storage import (
    StorageCandidateFact,
    StorageDependencyFact,
    StoragePressureDecision,
    StorageScope,
)
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.media_jobs import _artifact_from_row
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    ExportBundleArtifactRow,
    FeatureArtifactRow,
    MediaJobRow,
    PreviewCandidateRow,
    RevisionRow,
    StorageEventRow,
)


class PostgresStorageUnitOfWork:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresStorageTransaction:
        return PostgresStorageTransaction(self._session_factory())


class PostgresStorageTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()

    async def load_storage_facts(
        self,
        *,
        project_id: UUID,
        dependency_artifact_ids: tuple[UUID, ...],
        now: datetime,
    ) -> tuple[
        int,
        int,
        int,
        tuple[StorageDependencyFact, ...],
        tuple[StorageCandidateFact, ...],
    ]:
        active_source_job_ids = set(
            (
                await self._session.execute(
                    select(MediaJobRow.id).where(
                        MediaJobRow.status == JobStatus.RUNNING.value,
                        MediaJobRow.lease_expires_at.is_not(None),
                        MediaJobRow.lease_expires_at > now,
                    )
                )
            ).scalars()
        )
        active_job_payloads = (
            (
                await self._session.execute(
                    select(MediaJobRow.input_payload).where(
                        MediaJobRow.status == JobStatus.RUNNING.value,
                        MediaJobRow.lease_expires_at.is_not(None),
                        MediaJobRow.lease_expires_at > now,
                    )
                )
            )
            .scalars()
            .all()
        )
        active_artifact_refs = {
            item
            for payload in active_job_payloads
            for item in _uuid_values(payload)
        }
        audio_usage = (
            await self._session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    AudioArtifactRow.availability
                                    == ArtifactAvailability.AVAILABLE.value,
                                    AudioArtifactRow.byte_size,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (AudioArtifactRow.project_id == project_id)
                                    & (
                                        AudioArtifactRow.availability
                                        == ArtifactAvailability.AVAILABLE.value
                                    ),
                                    AudioArtifactRow.byte_size,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
            )
        ).one()
        feature_usage = (
            await self._session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    FeatureArtifactRow.availability
                                    == ArtifactAvailability.AVAILABLE.value,
                                    FeatureArtifactRow.byte_size,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (FeatureArtifactRow.project_id == project_id)
                                    & (
                                        FeatureArtifactRow.availability
                                        == ArtifactAvailability.AVAILABLE.value
                                    ),
                                    FeatureArtifactRow.byte_size,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
            )
        ).one()
        bundle_usage = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(ExportBundleArtifactRow.byte_size), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    ExportBundleArtifactRow.project_id == project_id,
                                    ExportBundleArtifactRow.byte_size,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    ExportBundleArtifactRow.availability
                    == ArtifactAvailability.AVAILABLE.value
                )
            )
        ).one()
        rows = (
            await self._session.execute(
                select(AudioArtifactRow).where(
                    AudioArtifactRow.availability == ArtifactAvailability.AVAILABLE.value,
                    AudioArtifactRow.lifecycle_class == ArtifactLifecycle.REBUILDABLE.value,
                )
            )
        ).scalars()
        feature_rows = (
            await self._session.execute(
                select(FeatureArtifactRow).where(
                    FeatureArtifactRow.availability == ArtifactAvailability.AVAILABLE.value,
                    FeatureArtifactRow.lifecycle_class == ArtifactLifecycle.REBUILDABLE.value,
                )
            )
        ).scalars()
        candidates = tuple(
            StorageCandidateFact(
                artifact_id=row.id,
                project_id=row.project_id,
                byte_size=row.byte_size,
                scope=StorageScope.ARTIFACT,
                lifecycle_class=ArtifactLifecycle(row.lifecycle_class),
                availability=ArtifactAvailability(row.availability),
                recipe_complete=row.rebuild_recipe is not None,
                rebuild_inputs_available=row.rebuild_recipe is not None,
                protection_reasons=tuple(row.protection_reasons),
                active_job_lease=(
                    row.source_job_id in active_source_job_ids
                    or row.rehydration_job_id in active_source_job_ids
                    or row.id in active_artifact_refs
                ),
                last_accessed_at=row.last_accessed_at or row.created_at,
                expires_at=row.expires_at,
            )
            for row in (*rows, *feature_rows)
        )
        dependency_rows = (
            (
                await self._session.execute(
                    select(AudioArtifactRow).where(
                        AudioArtifactRow.id.in_(dependency_artifact_ids),
                        AudioArtifactRow.project_id == project_id,
                    )
                )
            )
            .scalars()
            .all()
            if dependency_artifact_ids
            else []
        )
        by_id = {row.id: row for row in dependency_rows}
        dependencies: list[StorageDependencyFact] = []
        for artifact_id in dependency_artifact_ids:
            row = by_id.get(artifact_id)
            if row is None:
                dependencies.append(
                    StorageDependencyFact(
                        artifact_id=artifact_id,
                        availability=ArtifactAvailability.MISSING,
                    )
                )
                continue
            recipe = row.rebuild_recipe
            dependencies.append(
                StorageDependencyFact(
                    artifact_id=artifact_id,
                    availability=ArtifactAvailability(row.availability),
                    rehydratable=(
                        row.lifecycle_class == ArtifactLifecycle.REBUILDABLE.value
                        and recipe is not None
                        and await self._recipe_inputs_available(recipe)
                    ),
                )
            )
        return (
            int(audio_usage[0]) + int(feature_usage[0]) + int(bundle_usage[0]),
            int(audio_usage[1]) + int(feature_usage[1]) + int(bundle_usage[1]),
            0,
            tuple(dependencies),
            candidates,
        )

    async def _recipe_inputs_available(self, recipe: dict[str, object]) -> bool:
        raw_inputs = recipe.get("input_artifacts", [])
        if not isinstance(raw_inputs, list) or not raw_inputs:
            return False
        try:
            input_ids = tuple(UUID(str(item["artifact_id"])) for item in raw_inputs)
        except (KeyError, TypeError, ValueError):
            return False
        count = int(
            (
                await self._session.execute(
                    select(func.count(AudioArtifactRow.id)).where(
                        AudioArtifactRow.id.in_(input_ids),
                        AudioArtifactRow.availability == ArtifactAvailability.AVAILABLE.value,
                    )
                )
            ).scalar_one()
        )
        return count == len(set(input_ids))
    async def record_storage_decision(self, decision: StoragePressureDecision) -> None:
        sequence = int(
            (
                await self._session.execute(
                    select(func.count(StorageEventRow.id)).where(
                        StorageEventRow.operation_id == decision.operation_id
                    )
                )
            ).scalar_one()
        )
        await self._session.execute(
            insert(StorageEventRow).values(
                id=uuid4(),
                project_id=decision.project_id,
                operation_id=decision.operation_id,
                sequence=sequence,
                event_type="storage.pressure_evaluated",
                policy_version=decision.policy_version,
                route=decision.route.value,
                explanation_code=decision.explanation_code,
                payload={
                    "matched_rule_id": decision.matched_rule_id,
                    "error_code": decision.error_code,
                    "required_reclaim_bytes": decision.required_reclaim_bytes,
                    "planned_reclaim_bytes": decision.planned_reclaim_bytes,
                    "cleanup_artifact_ids": [str(item) for item in decision.cleanup_artifact_ids],
                    "rehydrate_artifact_ids": [
                        str(item) for item in decision.rehydrate_artifact_ids
                    ],
                    "protected_candidate_count": decision.protected_candidate_count,
                },
                created_at=datetime.now(UTC),
            )
        )

    async def lock_artifact_for_eviction(
        self, artifact_id: UUID
    ) -> AudioArtifact | FeatureArtifact | None:
        row = (
            await self._session.execute(
                select(AudioArtifactRow).where(AudioArtifactRow.id == artifact_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is not None:
            if await self._is_protected(row):
                return None
            return _artifact_from_row(row)
        feature = (
            await self._session.execute(
                select(FeatureArtifactRow)
                .where(FeatureArtifactRow.id == artifact_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if feature is None or feature.protection_reasons:
            return None
        from motif_forge.infrastructure.persistence.media_jobs import _feature_from_row

        return _feature_from_row(feature)

    async def mark_artifact_evicted(
        self, *, artifact_id: UUID, operation_id: str, evicted_at: datetime
    ) -> bool:
        audio_changed = (
            await self._session.execute(
                update(AudioArtifactRow)
                .where(
                    AudioArtifactRow.id == artifact_id,
                    AudioArtifactRow.availability == ArtifactAvailability.AVAILABLE.value,
                )
                .values(
                    availability=ArtifactAvailability.EVICTED.value,
                    evicted_at=evicted_at,
                    rehydration_job_id=None,
                )
                .returning(AudioArtifactRow.id)
            )
        ).scalar_one_or_none() is not None
        changed = audio_changed
        if not changed:
            changed = (
                await self._session.execute(
                    update(FeatureArtifactRow)
                    .where(
                        FeatureArtifactRow.id == artifact_id,
                        FeatureArtifactRow.availability
                        == ArtifactAvailability.AVAILABLE.value,
                    )
                    .values(
                        availability=ArtifactAvailability.EVICTED.value,
                        evicted_at=evicted_at,
                        rehydration_job_id=None,
                    )
                    .returning(FeatureArtifactRow.id)
                )
            ).scalar_one_or_none() is not None
        if changed:
            await self._session.execute(
                insert(StorageEventRow).values(
                    id=uuid4(),
                    project_id=(
                        await self._session.execute(
                            select(
                                func.coalesce(
                                    select(AudioArtifactRow.project_id)
                                    .where(AudioArtifactRow.id == artifact_id)
                                    .scalar_subquery(),
                                    select(FeatureArtifactRow.project_id)
                                    .where(FeatureArtifactRow.id == artifact_id)
                                    .scalar_subquery(),
                                )
                            )
                        )
                    ).scalar_one(),
                    operation_id=operation_id,
                    sequence=int(
                        (
                            await self._session.execute(
                                select(func.count(StorageEventRow.id)).where(
                                    StorageEventRow.operation_id == operation_id
                                )
                            )
                        ).scalar_one()
                    ),
                    event_type="artifact.evicted",
                    policy_version="storage-pressure-policy.v1",
                    route="gc_then_retry",
                    explanation_code="STORAGE_ARTIFACT_EVICTED",
                    payload={"artifact_id": str(artifact_id), "rehydratable": True},
                    created_at=evicted_at,
                )
            )
        return changed

    async def _is_protected(self, row: AudioArtifactRow) -> bool:
        if row.protection_reasons:
            return True
        artifact_id = str(row.id)
        revision_ref = (
            await self._session.execute(
                select(RevisionRow.id).where(
                    cast(RevisionRow.arrangement_ir, String).contains(artifact_id)
                )
            )
        ).first()
        if revision_ref is not None:
            return True
        preview_ref = (
            await self._session.execute(
                select(PreviewCandidateRow.id).where(
                    PreviewCandidateRow.status == "pending",
                    PreviewCandidateRow.preview_artifact_ids.contains([artifact_id]),
                )
            )
        ).first()
        if preview_ref is not None:
            return True
        recipe = row.rebuild_recipe or {}
        input_ids = [
            str(item.get("artifact_id"))
            for item in recipe.get("input_artifacts", [])
            if item.get("artifact_id")
        ]
        if input_ids:
            input_count = int(
                (
                    await self._session.execute(
                        select(func.count(AudioArtifactRow.id)).where(
                            AudioArtifactRow.id.in_([UUID(item) for item in input_ids]),
                            AudioArtifactRow.availability == ArtifactAvailability.AVAILABLE.value,
                        )
                    )
                ).scalar_one()
            )
            if input_count != len(input_ids):
                return True
        return False


def _uuid_values(value: object) -> set[UUID]:
    found: set[UUID] = set()
    if isinstance(value, dict):
        for nested in value.values():
            found.update(_uuid_values(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_uuid_values(nested))
    elif isinstance(value, str):
        with suppress(ValueError):
            found.add(UUID(value))
    return found
