from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from motif_forge.api.app import create_app
from motif_forge.application.errors import ApplicationError
from motif_forge.application.run_graph_history import RunGraphHistory, RunGraphTaskPath
from motif_forge.application.run_inspection import (
    InspectionEvent,
    InspectionRunSummary,
    RecoverySummary,
    RunInspectionFacts,
    RunUsageSummary,
    RunVersionSummary,
)
from motif_forge.config import Settings


def uid(value: int) -> UUID:
    return UUID(int=value)


class FakeInspectionStore:
    def __init__(self, *, run_type: str = "generate") -> None:
        self.run_type = run_type

    async def read_run_inspection(self, run_id: UUID) -> RunInspectionFacts | None:
        if run_id != uid(1):
            return None
        return RunInspectionFacts(
            run=InspectionRunSummary(
                run_id=run_id,
                project_id=uid(2),
                thread_id="thread-graph-api",
                run_type=self.run_type,
                status="succeeded",
                version=3,
                revision_id=uid(3),
                bundle_id=uid(4),
                error_code=None,
            ),
            versions=RunVersionSummary(
                graph_topology_version="motif-forge-parent.v2",
                state_schema_version="parent-state.v2",
            ),
            usage=RunUsageSummary(
                submitted_model_requests=0,
                max_model_requests=3,
                max_total_tokens=1000,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                usage_status="known",
                cost_status="known",
                cost_amount_microusd=0,
            ),
            timeline=(
                InspectionEvent(
                    sequence=1,
                    event_type="ai_run.updated",
                    phase="succeeded",
                    created_at=datetime(2026, 8, 31, tzinfo=UTC),
                    summary={},
                ),
            ),
            timeline_truncated=False,
            decisions=(),
            jobs=(),
            artifacts=(),
            recovery=RecoverySummary(
                resume_events=0,
                replay_events=0,
                retry_events=0,
                cancel_events=0,
                terminal_outcome="succeeded",
            ),
        )


class FakeHistoryStore:
    fail = False
    compatible = True

    async def read_run_graph_history(self, thread_id: str) -> RunGraphHistory:
        assert thread_id == "thread-graph-api"
        if self.fail:
            raise ApplicationError(
                "CHECKPOINT_HISTORY_READ_FAILED", "history unavailable", retryable=True
            )
        return RunGraphHistory(
            checkpoint_count=2,
            task_paths=(
                RunGraphTaskPath(
                    checkpoint_ns="",
                    checkpoint_id="1",
                    task_id="task-1",
                    task_path="~__pregel_pull, ValidateRequest",
                    technical_name="ValidateRequest",
                    path_kind="pull",
                ),
            )
            if self.compatible
            else (),
            truncated=False,
            schema_compatible=self.compatible,
        )


async def get_response(
    run_id: UUID,
    *,
    inspections: FakeInspectionStore | None = None,
    histories: FakeHistoryStore | None = None,
):
    app = create_app(
        Settings.for_test(),
        run_inspection_store=inspections or FakeInspectionStore(),
        run_graph_history_store=histories or FakeHistoryStore(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(f"/api/v1/runs/{run_id}/graph")


@pytest.mark.asyncio
async def test_graph_route_returns_versioned_safe_generate_projection() -> None:
    response = await get_response(uid(1))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["schema_version"] == "run-graph-view.v1"
    assert data["graph_kind"] == "generate"
    assert data["nodes"][0]["technical_name"] == "ValidateRequest"
    for forbidden in ("blob", "payload", "prompt", "approval_assertion", "storage_key"):
        assert forbidden not in response.text


@pytest.mark.asyncio
async def test_graph_route_maps_missing_unsupported_and_read_failure() -> None:
    missing = await get_response(uid(99))
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "AI_RUN_NOT_FOUND"

    unsupported = await get_response(uid(1), inspections=FakeInspectionStore(run_type="edit"))
    assert unsupported.status_code == 422
    assert unsupported.json()["error_code"] == "RUN_GRAPH_UNSUPPORTED"

    histories = FakeHistoryStore()
    histories.fail = True
    failed = await get_response(uid(1), histories=histories)
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "CHECKPOINT_HISTORY_READ_FAILED"


@pytest.mark.asyncio
async def test_incompatible_checkpoint_schema_is_a_partial_200_response() -> None:
    histories = FakeHistoryStore()
    histories.compatible = False
    response = await get_response(uid(1), histories=histories)

    assert response.status_code == 200
    assert response.json()["data"]["evidence_status"] == "partial"
    assert response.json()["data"]["evidence_summary"]["schema_compatible"] is False
