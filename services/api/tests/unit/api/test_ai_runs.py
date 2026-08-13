from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from motif_forge.api.app import create_app
from motif_forge.config import Settings
from motif_forge.domain.ai_runs import AIRun


class FakeAIRunTransaction:
    def __init__(self) -> None:
        self.run: AIRun | None = None
        self.outbox_creates = 0

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    async def get_ai_run_idempotency(self, *, project_id, key):  # type: ignore[no-untyped-def]
        from motif_forge.application._hashing import request_hash
        from motif_forge.application.ports import IdempotencyHit

        if self.run is None or self.run.project_id != project_id or self.run.idempotency_key != key:
            return None
        return IdempotencyHit(
            resource_id=self.run.run_id,
            request_hash=request_hash({
                "schema": "ai-run.create.v1",
                "project_id": str(self.run.project_id), "branch_id": str(self.run.branch_id),
                "base_revision_id": str(self.run.base_revision_id),
                "thread_id": self.run.thread_id, "brief": self.run.brief,
                "max_model_requests": self.run.max_model_requests,
                "max_total_tokens": self.run.max_total_tokens,
                "graph_topology_version": self.run.graph_topology_version,
                "state_schema_version": self.run.state_schema_version,
            }),
            result_payload={"run_id": str(self.run.run_id)},
        )

    async def create_ai_run(self, *, run, created_event, outbox_event_id, request_hash):  # type: ignore[no-untyped-def]
        del created_event, outbox_event_id, request_hash
        self.run = run
        self.outbox_creates += 1

    async def read_ai_run(self, run_id: UUID) -> AIRun:
        assert self.run is not None and self.run.run_id == run_id
        return self.run


class FakeAIRunUOW:
    def __init__(self) -> None:
        self.transaction = FakeAIRunTransaction()

    def __call__(self) -> FakeAIRunTransaction:
        return self.transaction


def test_create_ai_run_is_async_safe_and_forbids_runtime_internals() -> None:
    uow = FakeAIRunUOW()
    app = create_app(Settings(), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    body = {
        "branch_id": str(uuid4()),
        "base_revision_id": str(uuid4()),
        "brief": {
            "title": "Safe API", "purpose": "Generate a calm underscore",
            "style": "synth_ambient", "duration_seconds": 60, "moods": ("calm",),
            "meter": "4/4",
        },
    }
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/projects/{uuid4()}/ai-runs",
            headers={"Idempotency-Key": "generate-safe-1"}, json=body,
        )
        assert response.status_code == 202
        assert response.json()["data"]["status"] == "queued"
        assert uow.transaction.outbox_creates == 1
        replay = client.post(
            response.request.url,
            headers={"Idempotency-Key": "generate-safe-1"}, json=body,
        )
        assert replay.status_code == 202
        assert replay.json()["data"]["run_id"] == response.json()["data"]["run_id"]
        assert uow.transaction.outbox_creates == 1
        forbidden = client.post(
            f"/api/v1/projects/{uuid4()}/ai-runs",
            headers={"Idempotency-Key": "generate-safe-2"},
            json={**body, "model": "deepseek", "node_name": "planner"},
        )
        assert forbidden.status_code == 422
        assert uow.transaction.outbox_creates == 1


def test_create_rejects_unsupported_style_and_meter_before_persistence() -> None:
    uow = FakeAIRunUOW()
    app = create_app(Settings(), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    with TestClient(app) as client:
        for brief in (
            {"title": "Bad", "purpose": "Bad style", "style": "metal",
             "duration_seconds": 60, "moods": ["calm"]},
            {"title": "Bad", "purpose": "Bad meter", "style": "synth_ambient",
             "duration_seconds": 60, "moods": ["calm"], "meter": "7/8"},
        ):
            response = client.post(
                f"/api/v1/projects/{uuid4()}/ai-runs",
                headers={"Idempotency-Key": f"invalid-{uuid4().hex}"},
                json={"branch_id": str(uuid4()), "base_revision_id": str(uuid4()),
                      "brief": brief},
            )
            assert response.status_code == 422
    assert uow.transaction.run is None
    assert uow.transaction.outbox_creates == 0
