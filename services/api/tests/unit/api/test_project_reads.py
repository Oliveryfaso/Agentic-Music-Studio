from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from motif_forge.api.app import create_app
from motif_forge.application.project_reads import (
    DeliveryAsset,
    ProjectRunSummary,
    ProjectSummary,
    ProjectWorkspace,
    RevisionStudio,
    RevisionSummary,
)
from motif_forge.application.storage import StorageRootSnapshot
from motif_forge.config import Settings
from motif_forge.domain.ai_runs import AIRunStatus
from motif_forge.domain.ir import ArrangementIR
from motif_forge.domain.media_jobs import ArtifactAvailability
from motif_forge.domain.storage import StorageRootHealth


def uid(value: int) -> UUID:
    return UUID(int=value)


NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


class FakeProjectReadStore:
    def __init__(self) -> None:
        self.project_id = uid(1)
        self.revision_id = uid(3)
        run = ProjectRunSummary(run_id=uid(8), status=AIRunStatus.SUCCEEDED, updated_at=NOW)
        revision = RevisionSummary(
            revision_id=self.revision_id, parent_revision_id=uid(2), source_run_id=uid(8),
            reason_code="generate", author_kind="agent", created_by="generate-worker",
            created_at=NOW,
        )
        self.summary = ProjectSummary(
            project_id=self.project_id, name="API Project", status="active", updated_at=NOW,
            active_branch_id=uid(2), head_revision_id=self.revision_id,
            latest_run=run, has_playable_revision=True,
        )
        self.workspace = ProjectWorkspace(
            project_id=self.project_id, name="API Project", status="active", updated_at=NOW,
            active_branch_id=uid(2), head_revision_id=self.revision_id,
            revisions=(revision,), runs=(run,), recoverable_run=None,
        )
        self.studio = RevisionStudio(
            project_id=self.project_id, revision_id=self.revision_id,
            parent_revision_id=uid(2), source_run_id=uid(8), reason_code="generate",
            author_kind="agent", created_by="generate-worker", created_at=NOW,
            arrangement_ir=ArrangementIR(project_id=self.project_id),
            delivery_assets=(DeliveryAsset(
                artifact_id=uid(10), quality_profile="delivery-mp3.v1",
                media_type="audio/mpeg", availability=ArtifactAvailability.AVAILABLE,
                byte_size=2048, duration_milliseconds=30_000,
            ),), bundle_id=uid(11),
        )

    async def list_projects(self, *, limit: int) -> tuple[ProjectSummary, ...]:
        assert limit <= 50
        return (self.summary,)

    async def read_project(self, project_id: UUID) -> ProjectWorkspace | None:
        return self.workspace if project_id == self.project_id else None

    async def read_revision_studio(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionStudio | None:
        if project_id == self.project_id and revision_id == self.revision_id:
            return self.studio
        return None


def test_project_read_routes_serialize_only_public_data() -> None:
    store = FakeProjectReadStore()
    app = create_app(
        Settings(environment="test"), project_read_store=store,
        storage_root_inspector=lambda: StorageRootSnapshot(
            StorageRootHealth.READY, True, 999_999
        ),
    )

    with TestClient(app) as client:
        listed = client.get("/api/v1/projects?limit=50")
        workspace = client.get(f"/api/v1/projects/{store.project_id}")
        studio = client.get(
            f"/api/v1/projects/{store.project_id}/revisions/{store.revision_id}/studio"
        )

    assert listed.status_code == workspace.status_code == studio.status_code == 200
    assert listed.json()["data"][0]["head_revision_id"] == str(store.revision_id)
    assert workspace.json()["data"]["storage_root_status"] == "ready"
    assert studio.json()["data"]["delivery_assets"][0]["media_type"] == "audio/mpeg"
    serialized = str((listed.json(), workspace.json(), studio.json()))
    assert "storage_key" not in serialized
    assert "storage_prefix" not in serialized
    assert "worker_payload" not in serialized
    assert "/Volumes/" not in serialized


def test_project_read_routes_validate_limit_and_revision_lineage() -> None:
    store = FakeProjectReadStore()
    app = create_app(Settings(environment="test"), project_read_store=store)

    with TestClient(app) as client:
        invalid_limit = client.get("/api/v1/projects?limit=51")
        wrong_project = client.get(f"/api/v1/projects/{uid(99)}")
        wrong_lineage = client.get(
            f"/api/v1/projects/{uid(99)}/revisions/{store.revision_id}/studio"
        )

    assert invalid_limit.status_code == 422
    assert wrong_project.status_code == 404
    assert wrong_lineage.status_code == 404
    assert wrong_lineage.json()["error_code"] == "REVISION_NOT_FOUND"


def test_project_read_openapi_uses_frozen_public_data_names() -> None:
    schemas = create_app(
        Settings(environment="test"), project_read_store=FakeProjectReadStore()
    ).openapi()["components"]["schemas"]

    assert {"ProjectSummaryData", "ProjectWorkspaceData", "RevisionStudioData"} <= set(schemas)
