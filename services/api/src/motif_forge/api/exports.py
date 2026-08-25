"""Public S7 Export read and delivery routes."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from motif_forge.application.export_reads import (
    ExportProjectionStore,
    ReadRevisionExport,
    ResolveBundleFile,
    RevisionExportProjection,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RevisionExportResponse(ApiModel):
    data: RevisionExportProjection


def build_export_router(store: ExportProjectionStore, *, artifact_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["exports"])

    @router.get(
        "/projects/{project_id}/revisions/{revision_id}/exports",
        response_model=RevisionExportResponse,
    )
    async def read_revision_export(
        project_id: UUID, revision_id: UUID
    ) -> RevisionExportResponse:
        return RevisionExportResponse(data=await ReadRevisionExport(store)(
            project_id=project_id, revision_id=revision_id
        ))

    @router.get(
        "/export-bundles/{bundle_id}/files/{filename}", response_class=FileResponse
    )
    async def read_bundle_file(bundle_id: UUID, filename: str) -> FileResponse:
        content = await ResolveBundleFile(store, artifact_root=artifact_root)(
            bundle_id, filename
        )
        return FileResponse(
            content.path, media_type=content.media_type, filename=content.filename,
            content_disposition_type="attachment", headers={"Cache-Control": "private, no-store"},
        )

    return router
