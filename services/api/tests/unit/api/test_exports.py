from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from motif_forge.api.app import create_app
from motif_forge.application.export_reads import (
    ExportBundleSummary,
    ExportFileSummary,
    ExportStepSummary,
    RevisionExportProjection,
    StoredExportBundle,
)
from motif_forge.application.generation import EXPORT_STEPS
from motif_forge.config import Settings
from motif_forge.domain.media_jobs import ArtifactAvailability


def uid(value: int) -> UUID:
    return UUID(int=value)


class FakeExportStore:
    projection: RevisionExportProjection | None = None

    async def read_revision_export(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionExportProjection | None:
        return self.projection

    async def read_bundle(self, bundle_id: UUID) -> StoredExportBundle | None:
        return None


def ready_projection() -> RevisionExportProjection:
    return RevisionExportProjection(
        project_id=uid(1), revision_id=uid(2), source_run_id=uid(3), status="ready",
        bundle=ExportBundleSummary(
            bundle_id=uid(20), project_id=uid(1), revision_id=uid(2),
            availability=ArtifactAvailability.AVAILABLE, content_hash="a" * 64,
            byte_size=100, file_count=13,
        ),
        steps=tuple(
            ExportStepSummary(step=step, job_id=uid(100 + index), status="succeeded",
                              artifact_id=uid(200 + index), error_code=None)
            for index, step in enumerate(EXPORT_STEPS)
        ),
        files=(ExportFileSummary(
            file_id=f"audio:{uid(200)}", filename="master.wav", category="master",
            media_type="audio/wav", byte_size=12,
            availability=ArtifactAvailability.AVAILABLE, checksum="b" * 64,
            content_url=f"/api/v1/audio-artifacts/{uid(200)}/content",
            artifact_id=uid(200),
        ),),
    )


def test_export_route_serializes_projection_without_storage_paths(tmp_path: Path) -> None:
    store = FakeExportStore()
    store.projection = ready_projection()
    app = create_app(Settings.for_test(artifact_root=tmp_path), export_read_store=store)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/projects/{uid(1)}/revisions/{uid(2)}/exports")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert len(response.json()["data"]["steps"]) == 7
    serialized = response.text
    assert "storage_prefix" not in serialized
    assert "storage_key" not in serialized
    assert str(tmp_path) not in serialized


def test_export_openapi_names_frozen_projection(tmp_path: Path) -> None:
    store = FakeExportStore()
    schemas = create_app(
        Settings.for_test(artifact_root=tmp_path), export_read_store=store
    ).openapi()["components"]["schemas"]

    assert "RevisionExportProjection" in schemas
