from __future__ import annotations

import pytest
from motif_forge.application.errors import IdempotencyKeyReusedError
from motif_forge.application.projects import CreateProject, CreateProjectRequest

from .fakes import FakeTransaction


@pytest.mark.asyncio
async def test_create_project_atomically_creates_root_branch_and_audit() -> None:
    transaction = FakeTransaction()
    create_project = CreateProject(transaction)

    result = await create_project(
        CreateProjectRequest(
            name="Night Signals", actor_id="local-user", idempotency_key="create-001"
        )
    )

    root = transaction.roots[result.project_id]
    assert root.active_branch_id == result.active_branch_id
    assert root.revision.revision_id == result.root_revision_id
    assert root.branch.head_revision_id == result.root_revision_id
    assert transaction.audit_events == [("project.created", result.project_id)]
    assert not result.replayed


@pytest.mark.asyncio
async def test_create_project_replays_same_result_for_same_key() -> None:
    transaction = FakeTransaction()
    create_project = CreateProject(transaction)
    request = CreateProjectRequest(
        name="Night Signals", actor_id="local-user", idempotency_key="create-001"
    )

    first = await create_project(request)
    replay = await create_project(request)

    assert replay.project_id == first.project_id
    assert replay.root_revision_id == first.root_revision_id
    assert replay.replayed
    assert len(transaction.roots) == 1


@pytest.mark.asyncio
async def test_create_project_rejects_reused_key_with_changed_payload() -> None:
    transaction = FakeTransaction()
    create_project = CreateProject(transaction)
    await create_project(
        CreateProjectRequest(name="First", actor_id="local-user", idempotency_key="create-001")
    )

    with pytest.raises(IdempotencyKeyReusedError) as raised:
        await create_project(
            CreateProjectRequest(name="Second", actor_id="local-user", idempotency_key="create-001")
        )

    assert raised.value.code == "IDEMPOTENCY_KEY_REUSED"
