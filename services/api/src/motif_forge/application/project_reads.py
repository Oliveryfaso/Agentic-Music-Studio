"""Bounded, transport-independent read models for Project Home and Studio."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from motif_forge.application.errors import ApplicationError
from motif_forge.application.storage import StorageRootSnapshot
from motif_forge.domain.ai_runs import AIRunStatus
from motif_forge.domain.ir import ArrangementIR
from motif_forge.domain.media_jobs import ArtifactAvailability
from motif_forge.domain.storage import StorageRootHealth


class ProjectReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectRunSummaryData(ProjectReadModel):
    run_id: UUID
    status: AIRunStatus
    updated_at: datetime


class RevisionSummaryData(ProjectReadModel):
    revision_id: UUID
    parent_revision_id: UUID | None
    source_run_id: UUID | None
    reason_code: str
    author_kind: str
    created_by: str
    created_at: datetime


class ProjectSummaryData(ProjectReadModel):
    project_id: UUID
    name: str
    status: str
    updated_at: datetime
    active_branch_id: UUID
    head_revision_id: UUID
    latest_run: ProjectRunSummaryData | None
    has_playable_revision: bool


class ProjectWorkspace(ProjectReadModel):
    project_id: UUID
    name: str
    status: str
    updated_at: datetime
    active_branch_id: UUID
    head_revision_id: UUID
    revisions: tuple[RevisionSummaryData, ...] = Field(max_length=20)
    runs: tuple[ProjectRunSummaryData, ...] = Field(max_length=10)
    recoverable_run: ProjectRunSummaryData | None


class ProjectWorkspaceData(ProjectWorkspace):
    storage_root_status: StorageRootHealth


class DeliveryAsset(ProjectReadModel):
    artifact_id: UUID
    quality_profile: Literal["delivery-mp3.v1"]
    media_type: Literal["audio/mpeg"]
    availability: ArtifactAvailability
    byte_size: int = Field(ge=0)
    duration_milliseconds: int | None = Field(default=None, ge=0)


class RevisionStudioData(ProjectReadModel):
    project_id: UUID
    revision_id: UUID
    parent_revision_id: UUID | None
    source_run_id: UUID | None
    reason_code: str
    author_kind: str
    created_by: str
    created_at: datetime
    arrangement_ir: ArrangementIR
    delivery_assets: tuple[DeliveryAsset, ...]
    bundle_id: UUID | None

    @field_validator("arrangement_ir", mode="before")
    @classmethod
    def validate_stored_ir(cls, value: object) -> ArrangementIR:
        if isinstance(value, ArrangementIR):
            return value
        return ArrangementIR.model_validate_json(json.dumps(value), strict=True)


ProjectRunSummary = ProjectRunSummaryData
RevisionSummary = RevisionSummaryData
ProjectSummary = ProjectSummaryData
RevisionStudio = RevisionStudioData


class ProjectReadStore(Protocol):
    async def list_projects(self, *, limit: int) -> tuple[ProjectSummary, ...]: ...

    async def read_project(self, project_id: UUID) -> ProjectWorkspace | None: ...

    async def read_revision_studio(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionStudio | None: ...


class ListProjects:
    def __init__(self, store: ProjectReadStore) -> None:
        self._store = store

    async def __call__(self, *, limit: int = 50) -> tuple[ProjectSummary, ...]:
        if not 1 <= limit <= 50:
            raise ApplicationError(
                "PROJECT_LIST_LIMIT_INVALID", "project list limit must be between 1 and 50"
            )
        return await self._store.list_projects(limit=limit)


class ReadProjectWorkspace:
    def __init__(
        self,
        store: ProjectReadStore,
        inspect_storage_root: Callable[[], StorageRootSnapshot],
    ) -> None:
        self._store = store
        self._inspect_storage_root = inspect_storage_root

    async def __call__(self, project_id: UUID) -> ProjectWorkspaceData:
        project = await self._store.read_project(project_id)
        if project is None:
            raise ApplicationError("PROJECT_NOT_FOUND", "the project does not exist")
        return ProjectWorkspaceData(
            **project.model_dump(mode="python"),
            storage_root_status=self._inspect_storage_root().health,
        )


class ReadRevisionStudio:
    def __init__(self, store: ProjectReadStore) -> None:
        self._store = store

    async def __call__(self, *, project_id: UUID, revision_id: UUID) -> RevisionStudio:
        studio = await self._store.read_revision_studio(
            project_id=project_id, revision_id=revision_id
        )
        if studio is None:
            raise ApplicationError(
                "REVISION_NOT_FOUND", "the revision does not belong to the project"
            )
        return studio
