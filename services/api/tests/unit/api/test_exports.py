from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
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
        project_id=uid(1),
        revision_id=uid(2),
        source_run_id=uid(3),
        status="ready",
        bundle=ExportBundleSummary(
            bundle_id=uid(20),
            project_id=uid(1),
            revision_id=uid(2),
            availability=ArtifactAvailability.AVAILABLE,
            content_hash="a" * 64,
            byte_size=100,
            file_count=13,
        ),
        steps=tuple(
            ExportStepSummary(
                step=step,
                job_id=uid(100 + index),
                status="succeeded",
                artifact_id=uid(200 + index),
                error_code=None,
            )
            for index, step in enumerate(EXPORT_STEPS)
        ),
        files=(
            ExportFileSummary(
                file_id=f"audio:{uid(200)}",
                filename="master.wav",
                category="master",
                media_type="audio/wav",
                byte_size=12,
                availability=ArtifactAvailability.AVAILABLE,
                checksum="b" * 64,
                content_url=f"/api/v1/audio-artifacts/{uid(200)}/content",
                artifact_id=uid(200),
            ),
        ),
    )


def test_export_route_serializes_projection_without_storage_paths(tmp_path: Path) -> None:
    store = FakeExportStore()
    store.projection = ready_projection()
    app = create_app(
        Settings.for_test(artifact_root=tmp_path, postgres_dsn=None), export_read_store=store
    )

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
        Settings.for_test(artifact_root=tmp_path, postgres_dsn=None), export_read_store=store
    ).openapi()["components"]["schemas"]

    assert "RevisionExportProjection" in schemas


@pytest.mark.asyncio
@pytest.mark.parametrize("committed_before_crash", [False, True])
async def test_same_key_resumes_prepared_checkpoint_without_repeating_side_effect(
    tmp_path: Path, committed_before_crash: bool
) -> None:
    from httpx import ASGITransport, AsyncClient
    from langgraph.checkpoint.memory import InMemorySaver
    from motif_forge.agent.parent_graph import build_parent_graph
    from motif_forge.domain.export_plan import CompleteExportCursorV2, ExportPlanV2

    saved = None
    enqueues = 0
    effects = 0

    async def prepare(request, *, thread_id):
        plan = ExportPlanV2(
            project_id=request.project_id,
            revision_id=request.revision_id,
            request_id=request.request_id,
            arrangement_hash="a" * 64,
            seed=0,
            track_ids=(uid(50),),
            include_mp3=False,
        )
        return CompleteExportCursorV2(
            plan=plan, plan_hash=plan.content_hash, thread_id=thread_id, run_type="parent.export.v1"
        )

    async def enqueue(cursor):
        nonlocal saved, enqueues, effects
        enqueues += 1
        if enqueues == 1 and not committed_before_crash:
            raise RuntimeError("simulated node interruption before transaction")
        if saved is None:
            effects += 1
            saved = cursor.model_copy(
                update={
                    "media_run_id": uid(60),
                    "pending_job_id": uid(70),
                    "pending_idempotency_key": "finite-key",
                }
            )
        if enqueues == 1:
            raise RuntimeError("simulated node interruption after transaction")
        return saved

    async def unused(*args, **kwargs):
        raise AssertionError("unexpected service")

    app = create_app(
        Settings.for_test(postgres_dsn=None, artifact_root=tmp_path),
        export_read_store=FakeExportStore(),
    )
    app.state.parent_graph = build_parent_graph(
        unused,
        checkpointer=InMemorySaver(),
        prepare_revision_export=prepare,
        cancel_revision_export=unused,
        enqueue_next_complete_export_job=enqueue,
        collect_complete_export_artifact=unused,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        url = f"/api/v1/projects/{uid(1)}/revisions/{uid(2)}/exports"
        first = await client.post(
            url, json={"include_mp3": False}, headers={"Idempotency-Key": "recover-node-key"}
        )
        assert first.status_code == 500
        second = await client.post(
            url, json={"include_mp3": False}, headers={"Idempotency-Key": "recover-node-key"}
        )
        assert second.status_code == 202, second.text
        assert second.json()["data"]["phase"] == "waiting_export_worker"
        assert second.json()["data"]["pending_job_id"] == str(uid(70))
        assert enqueues == 2 and effects == 1
