from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from application.fakes import FakeTransaction
from httpx import ASGITransport, AsyncClient
from motif_forge.api.app import create_app
from motif_forge.config import Settings


class _ConfirmationGraph:
    async def aget_state(self, config: object) -> object:
        del config
        return SimpleNamespace(values={"phase": "analysis_confirmation_required"})

    async def ainvoke(self, command: object, config: object) -> dict[str, object]:
        del command, config
        return {
            "thread_id": "import-confirmation-test",
            "run_id": str(uuid4()),
            "phase": "waiting_worker",
            "pending_job_id": str(uuid4()),
            "artifact_refs": [],
            "analysis_policy_version": "import-analysis-policy.v1",
            "source_bpm": 100.0,
            "project_bpm": 120.0,
            "bpm_confidence": 0.4,
            "key_confidence": 0.3,
            "analysis_explanation_code": "IMPORT_ANALYSIS_USER_OVERRIDE",
        }


class _ReadableImportGraph:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    async def aget_state(self, config: object) -> object:
        del config
        return SimpleNamespace(values=self.values)


def _add_track_command(*, actor_kind: str = "human") -> dict[str, object]:
    return {
        "command_id": str(uuid4()),
        "command_type": "add_track",
        "schema_version": "editor-command.v1",
        "selection": {},
        "actor_kind": actor_kind,
        "client_sequence": 0,
        "payload": {
            "track": {
                "track_id": str(uuid4()),
                "track_type": "instrument",
                "name": "Keys",
                "role": "harmony",
                "instrument_ref": "builtin:piano",
            }
        },
    }


async def _create_project(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/projects",
        headers={"Idempotency-Key": "create-project-001"},
        json={"name": "Night Signals"},
    )
    assert response.status_code == 201
    return response.json()["data"]


@pytest.mark.asyncio
async def test_project_create_is_idempotent_and_uses_success_envelope() -> None:
    transaction = FakeTransaction()
    transport = ASGITransport(app=create_app(Settings.for_test(), uow_factory=transaction))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/projects",
            headers={"Idempotency-Key": "create-project-001"},
            json={"name": "Night Signals"},
        )
        replay = await client.post(
            "/api/v1/projects",
            headers={"Idempotency-Key": "create-project-001"},
            json={"name": "Night Signals"},
        )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["data"]["project_id"] == first.json()["data"]["project_id"]
    assert replay.json()["data"]["replayed"] is True
    assert first.headers["X-Request-ID"]
    assert first.headers["X-Trace-ID"]


@pytest.mark.asyncio
async def test_human_l1_command_batch_advances_branch() -> None:
    transaction = FakeTransaction()
    transport = ASGITransport(app=create_app(Settings.for_test(), uow_factory=transaction))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = await _create_project(client)
        response = await client.post(
            f"/api/v1/projects/{project['project_id']}/command-batches",
            headers={"Idempotency-Key": "commit-command-001"},
            json={
                "branch_id": project["active_branch_id"],
                "base_revision_id": project["root_revision_id"],
                "commands": [_add_track_command()],
                "client_sequence": 0,
                "reason": "TRACK_ADDED",
            },
        )

    assert response.status_code == 201
    assert response.json()["data"]["actual_change_impact"] == "L1"
    assert response.json()["data"]["render_state"] == "dirty"
    branch_id = UUID(project["active_branch_id"])
    assert (
        str(transaction.branches[branch_id].head_revision_id)
        == response.json()["data"]["revision_id"]
    )


@pytest.mark.asyncio
async def test_stale_base_returns_problem_details_with_current_revision() -> None:
    transaction = FakeTransaction()
    transport = ASGITransport(app=create_app(Settings.for_test(), uow_factory=transaction))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = await _create_project(client)
        response = await client.post(
            f"/api/v1/projects/{project['project_id']}/command-batches",
            headers={"Idempotency-Key": "commit-command-001"},
            json={
                "branch_id": project["active_branch_id"],
                "base_revision_id": str(uuid4()),
                "commands": [_add_track_command()],
                "client_sequence": 0,
                "reason": "TRACK_ADDED",
            },
        )

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["error_code"] == "REVISION_CONFLICT"
    assert response.json()["current_revision_id"] == project["root_revision_id"]


@pytest.mark.asyncio
async def test_public_command_endpoint_rejects_agent_actor() -> None:
    transaction = FakeTransaction()
    transport = ASGITransport(app=create_app(Settings.for_test(), uow_factory=transaction))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = await _create_project(client)
        response = await client.post(
            f"/api/v1/projects/{project['project_id']}/command-batches",
            headers={"Idempotency-Key": "commit-command-001"},
            json={
                "branch_id": project["active_branch_id"],
                "base_revision_id": project["root_revision_id"],
                "commands": [_add_track_command(actor_kind="agent")],
                "client_sequence": 0,
                "reason": "AI_TRACK_ADDED",
            },
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "COMMAND_ACTOR_INVALID"
    assert not transaction.command_batches


@pytest.mark.asyncio
async def test_import_analysis_confirmation_resumes_existing_parent_thread() -> None:
    app = create_app(Settings.for_test())
    app.state.parent_graph = _ConfirmationGraph()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/imports/import-{'a' * 32}/confirm-analysis",
            json={
                "action": "override",
                "source_bpm": 100.0,
                "key_tonic": "C",
                "key_mode": "major",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["phase"] == "waiting_worker"
    assert response.json()["data"]["analysis"]["policy_version"] == ("import-analysis-policy.v1")


@pytest.mark.asyncio
async def test_import_run_read_projects_stable_checkpoint_without_resuming_graph() -> None:
    run_id = uuid4()
    job_id = uuid4()
    artifact_id = uuid4()
    source_artifact_id = uuid4()
    normalized_artifact_id = uuid4()
    revision_id = uuid4()
    app = create_app(Settings.for_test())
    app.state.parent_graph = _ReadableImportGraph(
        {
            "operation": "import_audio",
            "run_id": str(run_id),
            "phase": "completed",
            "pending_job_id": str(job_id),
            "artifact_refs": [str(artifact_id)],
            "request_payload": {"source_artifact_id": str(source_artifact_id)},
            "normalized_artifact_id": str(normalized_artifact_id),
            "materialized_revision_id": str(revision_id),
            "analysis_policy_version": "import-analysis-policy.v1",
            "source_bpm": 112.0,
            "project_bpm": 120.0,
            "bpm_confidence": 0.8,
            "key_tonic": "D",
            "key_mode": "minor",
            "key_confidence": 0.4,
            "analysis_explanation_code": "IMPORT_ANALYSIS_ACCEPTED",
        }
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/imports/import-{'b' * 32}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["run_id"] == str(run_id)
    assert data["artifact_id"] == str(artifact_id)
    assert data["source_artifact_id"] == str(source_artifact_id)
    assert data["normalized_artifact_id"] == str(normalized_artifact_id)
    assert data["revision_id"] == str(revision_id)
    assert data["analysis"]["bpm"] == 112.0


@pytest.mark.asyncio
async def test_import_run_read_rejects_missing_or_wrong_operation_checkpoint() -> None:
    app = create_app(Settings.for_test())
    app.state.parent_graph = _ReadableImportGraph(
        {"operation": "artifact_rehydrate", "phase": "completed"}
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/imports/import-{'c' * 32}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "IMPORT_RUN_NOT_FOUND"


@pytest.mark.asyncio
async def test_project_write_without_postgres_configuration_returns_503() -> None:
    transport = ASGITransport(app=create_app(Settings.for_test(postgres_dsn=None)))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/projects",
            headers={"Idempotency-Key": "create-project-001"},
            json={"name": "Night Signals"},
        )

    assert response.status_code == 503
    assert response.json()["error_code"] == "PERSISTENCE_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_missing_idempotency_header_uses_problem_details() -> None:
    transaction = FakeTransaction()
    transport = ASGITransport(app=create_app(Settings.for_test(), uow_factory=transaction))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/projects", json={"name": "Night Signals"})

    assert response.status_code == 422
    assert response.json()["error_code"] == "REQUEST_VALIDATION_FAILED"
