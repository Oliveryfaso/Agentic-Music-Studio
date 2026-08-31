from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from motif_forge.api.run_inspection import build_run_inspection_router
from motif_forge.application.run_inspection import (
    InspectionEvent,
    InspectionRunSummary,
    RecoverySummary,
    RunInspectionFacts,
    RunUsageSummary,
    RunVersionSummary,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


class FakeInspectionStore:
    facts: RunInspectionFacts | None = None

    async def read_run_inspection(self, run_id: UUID) -> RunInspectionFacts | None:
        return self.facts if self.facts and self.facts.run_id == run_id else None


def facts() -> RunInspectionFacts:
    return RunInspectionFacts(
        run=InspectionRunSummary(
            run_id=uid(1), project_id=uid(2), thread_id="thread-generate-1",
            run_type="generate", status="succeeded",
            version=5, revision_id=uid(3), bundle_id=uid(4), error_code=None,
        ),
        versions=RunVersionSummary(
            graph_topology_version="motif-forge-parent.v2",
            state_schema_version="parent-state.v2",
        ),
        usage=RunUsageSummary(
            submitted_model_requests=0, max_model_requests=3, max_total_tokens=12_000,
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            usage_status="known", cost_status="known", cost_amount_microusd=0,
        ),
        timeline=(InspectionEvent(
            sequence=1, event_type="ai_run.created", phase="queued",
            created_at=datetime(2026, 8, 25, tzinfo=UTC), summary={},
        ),), timeline_truncated=False, decisions=(), jobs=(), artifacts=(),
        recovery=RecoverySummary(
            resume_events=0, replay_events=0, retry_events=0, cancel_events=0,
            terminal_outcome="succeeded",
        ),
    )


def test_run_inspection_route_combines_authoritative_run_and_safe_facts() -> None:
    store = FakeInspectionStore()
    store.facts = facts()
    app = FastAPI()
    app.include_router(build_run_inspection_router(store))

    with TestClient(app) as client:
        response = client.get(f"/api/v1/runs/{uid(1)}/inspect")

    assert response.status_code == 200
    assert response.json()["data"]["run"]["status"] == "succeeded"
    assert response.json()["data"]["run"]["thread_id"] == "thread-generate-1"
    assert response.json()["data"]["versions"]["graph_topology_version"] == "motif-forge-parent.v2"
    serialized = response.text
    for forbidden in ("approval_assertion", "storage_key", "/private/", '"prompt":'):
        assert forbidden not in serialized
