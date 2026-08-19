"""Bounded PostgreSQL queries for Project Home and read-only Studio."""

from __future__ import annotations

import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from motif_forge.application.errors import ApplicationError
from motif_forge.application.project_reads import (
    DeliveryAsset,
    ProjectRunSummary,
    ProjectSummary,
    ProjectWorkspace,
    RevisionStudio,
    RevisionSummary,
)
from motif_forge.domain.ai_runs import AIRunStatus
from motif_forge.domain.ir import ArrangementIR
from motif_forge.domain.media_jobs import ArtifactAvailability, MediaQualityProfile
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import (
    AIRunRow,
    AudioArtifactRow,
    BranchRow,
    ExportBundleArtifactRow,
    ProjectRow,
    RevisionRow,
)

RECOVERABLE_RUN_STATUSES = (
    AIRunStatus.QUEUED.value,
    AIRunStatus.PLANNING.value,
    AIRunStatus.WAITING_APPROVAL.value,
    AIRunStatus.MATERIALIZING.value,
    AIRunStatus.WAITING_WORKER.value,
)


class PostgresProjectReadStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_projects(self, *, limit: int) -> tuple[ProjectSummary, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(ProjectRow, BranchRow)
                    .join(
                        BranchRow,
                        (BranchRow.id == ProjectRow.active_branch_id)
                        & (BranchRow.project_id == ProjectRow.id),
                    )
                    .order_by(ProjectRow.updated_at.desc(), ProjectRow.id.desc())
                    .limit(limit)
                )
            ).all()
            if not rows:
                return ()
            project_ids = tuple(project.id for project, _ in rows)
            run_rows = (
                await session.execute(
                    select(AIRunRow)
                    .where(AIRunRow.project_id.in_(project_ids))
                    .order_by(
                        AIRunRow.project_id,
                        AIRunRow.updated_at.desc(),
                        AIRunRow.id.desc(),
                    )
                    .distinct(AIRunRow.project_id)
                )
            ).scalars()
            latest_runs: dict[UUID, ProjectRunSummary] = {}
            for run in run_rows:
                latest_runs.setdefault(run.project_id, _run_summary(run))
            playable_project_ids = set(
                (
                    await session.execute(
                        select(AudioArtifactRow.project_id)
                        .where(
                            AudioArtifactRow.project_id.in_(project_ids),
                            AudioArtifactRow.quality_profile
                            == MediaQualityProfile.DELIVERY_MP3_V1.value,
                            AudioArtifactRow.availability == ArtifactAvailability.AVAILABLE.value,
                        )
                        .distinct()
                    )
                ).scalars()
            )
            return tuple(
                ProjectSummary(
                    project_id=project.id,
                    name=project.name,
                    status=project.status,
                    updated_at=project.updated_at,
                    active_branch_id=project.active_branch_id,
                    head_revision_id=branch.head_revision_id,
                    latest_run=latest_runs.get(project.id),
                    has_playable_revision=project.id in playable_project_ids,
                )
                for project, branch in rows
            )

    async def read_project(self, project_id: UUID) -> ProjectWorkspace | None:
        async with self._session_factory() as session:
            project_branch = (
                await session.execute(
                    select(ProjectRow, BranchRow)
                    .join(
                        BranchRow,
                        (BranchRow.id == ProjectRow.active_branch_id)
                        & (BranchRow.project_id == ProjectRow.id),
                    )
                    .where(ProjectRow.id == project_id)
                )
            ).one_or_none()
            if project_branch is None:
                return None
            project, branch = project_branch
            revisions = tuple(
                _revision_summary(row)
                for row in (
                    await session.execute(
                        select(RevisionRow)
                        .where(RevisionRow.project_id == project_id)
                        .order_by(RevisionRow.created_at.desc(), RevisionRow.id.desc())
                        .limit(20)
                    )
                ).scalars()
            )
            runs = tuple(
                _run_summary(row)
                for row in (
                    await session.execute(
                        select(AIRunRow)
                        .where(AIRunRow.project_id == project_id)
                        .order_by(AIRunRow.updated_at.desc(), AIRunRow.id.desc())
                        .limit(10)
                    )
                ).scalars()
            )
            recoverable_row = (
                await session.execute(
                    select(AIRunRow)
                    .where(
                        AIRunRow.project_id == project_id,
                        AIRunRow.status.in_(RECOVERABLE_RUN_STATUSES),
                    )
                    .order_by(AIRunRow.updated_at.desc(), AIRunRow.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return ProjectWorkspace(
                project_id=project.id,
                name=project.name,
                status=project.status,
                updated_at=project.updated_at,
                active_branch_id=project.active_branch_id,
                head_revision_id=branch.head_revision_id,
                revisions=revisions,
                runs=runs,
                recoverable_run=(
                    _run_summary(recoverable_row) if recoverable_row is not None else None
                ),
            )

    async def read_revision_studio(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionStudio | None:
        async with self._session_factory() as session:
            revision = (
                await session.execute(
                    select(RevisionRow).where(
                        RevisionRow.id == revision_id,
                        RevisionRow.project_id == project_id,
                    )
                )
            ).scalar_one_or_none()
            if revision is None:
                return None
            asset_rows = (
                await session.execute(
                    select(AudioArtifactRow)
                    .where(
                        AudioArtifactRow.project_id == project_id,
                        AudioArtifactRow.revision_id == revision_id,
                        AudioArtifactRow.quality_profile
                        == MediaQualityProfile.DELIVERY_MP3_V1.value,
                    )
                    .order_by(AudioArtifactRow.created_at.desc(), AudioArtifactRow.id.desc())
                    .limit(10)
                )
            ).scalars()
            bundle_id = (
                await session.execute(
                    select(ExportBundleArtifactRow.id).where(
                        ExportBundleArtifactRow.project_id == project_id,
                        ExportBundleArtifactRow.revision_id == revision_id,
                    )
                )
            ).scalar_one_or_none()
            try:
                arrangement = ArrangementIR.model_validate_json(
                    json.dumps(revision.arrangement_ir), strict=True
                )
            except ValidationError:
                raise ApplicationError(
                    "REVISION_IR_INVALID", "the stored revision arrangement is invalid"
                ) from None
            return RevisionStudio(
                project_id=revision.project_id,
                revision_id=revision.id,
                parent_revision_id=revision.parent_id,
                source_run_id=revision.source_run_id,
                reason_code=revision.reason_code,
                author_kind=revision.author_kind,
                created_by=revision.created_by,
                created_at=revision.created_at,
                arrangement_ir=arrangement,
                delivery_assets=tuple(
                    DeliveryAsset(
                        artifact_id=asset.id,
                        quality_profile="delivery-mp3.v1",
                        media_type="audio/mpeg",
                        availability=ArtifactAvailability(asset.availability),
                        byte_size=asset.byte_size,
                        duration_milliseconds=asset.duration_milliseconds,
                    )
                    for asset in asset_rows
                ),
                bundle_id=bundle_id,
            )


def _run_summary(row: AIRunRow) -> ProjectRunSummary:
    return ProjectRunSummary(
        run_id=row.id, status=AIRunStatus(row.status), updated_at=row.updated_at
    )


def _revision_summary(row: RevisionRow) -> RevisionSummary:
    return RevisionSummary(
        revision_id=row.id,
        parent_revision_id=row.parent_id,
        source_run_id=row.source_run_id,
        reason_code=row.reason_code,
        author_kind=row.author_kind,
        created_by=row.created_by,
        created_at=row.created_at,
    )
