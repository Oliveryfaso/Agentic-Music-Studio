from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from motif_forge.application.errors import ChangeImpactEscalatedError, RevisionConflictError
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.domain.commands import AddTrackCommand, AddTrackPayload
from motif_forge.domain.ir import Track, TrackRole, TrackType
from motif_forge.domain.revisions import AuthorKind, ChangeImpact

from .fakes import FakeTransaction


async def _root(transaction: FakeTransaction) -> tuple[UUID, UUID]:
    result = await CreateProject(transaction)(
        CreateProjectRequest(name="Test", actor_id="local-user", idempotency_key="create-001")
    )
    return result.active_branch_id, result.root_revision_id


def _add_track(actor: str = "human") -> AddTrackCommand:
    return AddTrackCommand(
        command_id=uuid4(),
        actor_kind=actor,
        client_sequence=0,
        payload=AddTrackPayload(
            track=Track(
                track_id=uuid4(),
                track_type=TrackType.INSTRUMENT,
                name="Keys",
                role=TrackRole.HARMONY,
                instrument_ref="builtin:piano",
            )
        ),
    )


@pytest.mark.asyncio
async def test_commit_l1_batch_appends_revision_and_advances_branch() -> None:
    transaction = FakeTransaction()
    branch_id, base_revision_id = await _root(transaction)
    request = CommitCommandBatchRequest(
        project_id=next(iter(transaction.roots)),
        branch_id=branch_id,
        base_revision_id=base_revision_id,
        commands=(_add_track(),),
        actor_id="local-user",
        author_kind=AuthorKind.HUMAN,
        reason="TRACK_ADDED",
        idempotency_key="commit-001",
    )

    result = await CommitCommandBatch(transaction)(request)

    assert result.actual_change_impact is ChangeImpact.L1
    assert transaction.branches[branch_id].head_revision_id == result.revision_id
    assert transaction.revisions[result.revision_id].parent_revision_id == base_revision_id
    assert len(transaction.command_batches) == 1
    assert transaction.audit_events[-1][0] == "project.revision.committed"


@pytest.mark.asyncio
async def test_commit_replays_without_creating_second_revision() -> None:
    transaction = FakeTransaction()
    branch_id, base_revision_id = await _root(transaction)
    request = CommitCommandBatchRequest(
        project_id=next(iter(transaction.roots)),
        branch_id=branch_id,
        base_revision_id=base_revision_id,
        commands=(_add_track(),),
        actor_id="local-user",
        author_kind=AuthorKind.HUMAN,
        reason="TRACK_ADDED",
        idempotency_key="commit-001",
    )
    commit = CommitCommandBatch(transaction)

    first = await commit(request)
    replay = await commit(request)

    assert replay.revision_id == first.revision_id
    assert replay.replayed
    assert len(transaction.command_batches) == 1


@pytest.mark.asyncio
async def test_stale_base_returns_stable_revision_conflict() -> None:
    transaction = FakeTransaction()
    branch_id, _ = await _root(transaction)
    stale_revision_id = uuid4()
    request = CommitCommandBatchRequest(
        project_id=next(iter(transaction.roots)),
        branch_id=branch_id,
        base_revision_id=stale_revision_id,
        commands=(_add_track(),),
        actor_id="local-user",
        author_kind=AuthorKind.HUMAN,
        reason="TRACK_ADDED",
        idempotency_key="commit-001",
    )

    with pytest.raises(RevisionConflictError) as raised:
        await CommitCommandBatch(transaction)(request)

    assert raised.value.code == "REVISION_CONFLICT"
    assert raised.value.current_revision_id == transaction.branches[branch_id].head_revision_id
    assert not transaction.command_batches


@pytest.mark.asyncio
async def test_agent_creative_change_is_escalated_without_revision_write() -> None:
    transaction = FakeTransaction()
    branch_id, base_revision_id = await _root(transaction)
    request = CommitCommandBatchRequest(
        project_id=next(iter(transaction.roots)),
        branch_id=branch_id,
        base_revision_id=base_revision_id,
        commands=(_add_track("agent"),),
        actor_id="planner",
        author_kind=AuthorKind.AGENT,
        reason="AI_TRACK_ADDED",
        idempotency_key="commit-001",
    )

    with pytest.raises(ChangeImpactEscalatedError) as raised:
        await CommitCommandBatch(transaction)(request)

    assert raised.value.code == "CHANGE_IMPACT_ESCALATED"
    assert transaction.branches[branch_id].head_revision_id == base_revision_id
    assert not transaction.command_batches
