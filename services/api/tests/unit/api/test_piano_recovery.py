from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from motif_forge.api.project_reads import build_project_read_router
from motif_forge.application.piano_recovery import (
    PianoRecoveryDirectory,
    PianoRecoveryInfo,
    RecoverablePianoPreview,
)
from motif_forge.application.project_reads import ProjectWorkspace
from motif_forge.application.storage import StorageRootSnapshot
from motif_forge.domain.storage import StorageRootHealth

P, B, R = UUID(int=1), UUID(int=2), UUID(int=3)
NOW = datetime(2026, 10, 21, tzinfo=UTC)


class Store:
    async def read_project(self, project_id):
        assert project_id == P
        return ProjectWorkspace(
            project_id=P,
            name="Saved",
            status="active",
            updated_at=NOW,
            active_branch_id=B,
            head_revision_id=R,
            revisions=(),
            runs=(),
            recoverable_run=None,
        )


def test_workspace_wires_read_callback_and_reports_known_multiple_stale_base():
    calls = []

    async def discover(p, b):
        calls.append((p, b))
        return PianoRecoveryDirectory(
            recoverable=RecoverablePianoPreview(
                thread_id="piano-" + "a" * 32,
                branch_id=B,
                base_revision_id=UUID(int=4),
                phase="waiting_piano_approval",
                updated_at=NOW,
            ),
            recovery=PianoRecoveryInfo(status="ready", pending_count=2, reason_code=None),
        )

    app = FastAPI()
    app.include_router(
        build_project_read_router(
            Store(),
            lambda: StorageRootSnapshot(StorageRootHealth.READY, True, 1),
            piano_recovery=discover,
        )
    )
    with TestClient(app) as c:
        response = c.get(f"/api/v1/projects/{P}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["head_revision_id"] == str(R)
    assert data["recoverable_piano_preview"]["base_revision_id"] == str(UUID(int=4))
    assert data["piano_preview_recovery"] == dict(
        status="ready", pending_count=2, selection_rule="newest_created", reason_code=None
    )
    assert calls == [(P, B)]


def test_unwired_fake_store_does_not_pretend_directory_empty_or_ready():
    app = FastAPI()
    app.include_router(
        build_project_read_router(
            Store(), lambda: StorageRootSnapshot(StorageRootHealth.READY, True, 1)
        )
    )
    with TestClient(app) as c:
        response = c.get(f"/api/v1/projects/{P}")
    data = response.json()["data"]
    assert data["recoverable_piano_preview"] is None
    assert data["piano_preview_recovery"]["status"] == "unavailable"
    assert data["piano_preview_recovery"]["pending_count"] is None
