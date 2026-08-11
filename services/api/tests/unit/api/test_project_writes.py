from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from application.fakes import FakeTransaction
from httpx import ASGITransport, AsyncClient
from motif_forge.api.app import create_app
from motif_forge.config import Settings


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
    transport = ASGITransport(app=create_app(Settings(environment="test"), uow_factory=transaction))
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
    transport = ASGITransport(app=create_app(Settings(environment="test"), uow_factory=transaction))
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
    transport = ASGITransport(app=create_app(Settings(environment="test"), uow_factory=transaction))
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
    transport = ASGITransport(app=create_app(Settings(environment="test"), uow_factory=transaction))
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
async def test_project_write_without_postgres_configuration_returns_503() -> None:
    transport = ASGITransport(app=create_app(Settings(environment="test")))
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
    transport = ASGITransport(app=create_app(Settings(environment="test"), uow_factory=transaction))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/projects", json={"name": "Night Signals"})

    assert response.status_code == 422
    assert response.json()["error_code"] == "REQUEST_VALIDATION_FAILED"
