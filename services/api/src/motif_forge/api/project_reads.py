"""Public Project Home and read-only Studio routes."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from motif_forge.application.project_reads import (
    ListProjects,
    ProjectReadStore,
    ProjectSummary,
    ProjectWorkspaceData,
    ReadProjectWorkspace,
    ReadRevisionStudio,
    RevisionStudio,
)
from motif_forge.application.storage import StorageRootSnapshot


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectListResponse(ApiModel):
    data: tuple[ProjectSummary, ...]


class ProjectWorkspaceResponse(ApiModel):
    data: ProjectWorkspaceData


class RevisionStudioResponse(ApiModel):
    data: RevisionStudio


def build_project_read_router(
    store: ProjectReadStore,
    inspect_storage_root: Callable[[], StorageRootSnapshot],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["projects"])

    @router.get("/projects", response_model=ProjectListResponse)
    async def list_projects(limit: int = Query(default=50, ge=1, le=50)) -> ProjectListResponse:
        return ProjectListResponse(data=await ListProjects(store)(limit=limit))

    @router.get("/projects/{project_id}", response_model=ProjectWorkspaceResponse)
    async def read_project(project_id: UUID) -> ProjectWorkspaceResponse:
        return ProjectWorkspaceResponse(
            data=await ReadProjectWorkspace(store, inspect_storage_root)(project_id)
        )

    @router.get(
        "/projects/{project_id}/revisions/{revision_id}/studio",
        response_model=RevisionStudioResponse,
    )
    async def read_revision_studio(
        project_id: UUID, revision_id: UUID
    ) -> RevisionStudioResponse:
        return RevisionStudioResponse(
            data=await ReadRevisionStudio(store)(
                project_id=project_id, revision_id=revision_id
            )
        )

    return router
