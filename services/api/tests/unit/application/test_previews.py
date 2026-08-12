from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from motif_forge.application.errors import ApplicationError, RevisionConflictError
from motif_forge.application.previews import (
    CreateCommandPreview,
    CreateCommandPreviewRequest,
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.domain.commands import AddTrackCommand, AddTrackPayload
from motif_forge.domain.ir import Track, TrackRole, TrackType
from motif_forge.domain.revisions import AuthorKind, PreviewStatus

from .fakes import FakeTransaction

NOW = datetime(2026, 8, 11, 18, 0, tzinfo=UTC)


def _add_track(actor_kind: str, *, name: str) -> AddTrackCommand:
    return AddTrackCommand(
        command_id=uuid4(),
        actor_kind=actor_kind,
        client_sequence=0,
        payload=AddTrackPayload(
            track=Track(
                track_id=uuid4(),
                track_type=TrackType.INSTRUMENT,
                name=name,
                role=TrackRole.HARMONY,
                instrument_ref="builtin:piano",
            )
        ),
    )


async def _create_root(transaction: FakeTransaction) -> tuple[UUID, UUID, UUID]:
    created = await CreateProject(transaction)(
        CreateProjectRequest(name="Preview Test", actor_id="user", idempotency_key="create-001")
    )
    return created.project_id, created.active_branch_id, created.root_revision_id


async def _create_preview(
    transaction: FakeTransaction,
    *,
    clock: datetime = NOW,
) -> tuple[UUID, UUID, UUID, UUID]:
    project_id, branch_id, base_revision_id = await _create_root(transaction)
    created = await CreateCommandPreview(transaction, clock=lambda: clock)(
        CreateCommandPreviewRequest(
            project_id=project_id,
            branch_id=branch_id,
            base_revision_id=base_revision_id,
            candidate_id=uuid4(),
            commands=(_add_track("agent", name="AI Harmony"),),
            actor_id="agent:arranger",
            idempotency_key="preview-001",
        )
    )
    return project_id, branch_id, base_revision_id, created.preview_id


@pytest.mark.asyncio
async def test_l2_agent_change_creates_preview_without_advancing_branch() -> None:
    transaction = FakeTransaction()
    _, branch_id, base_revision_id, preview_id = await _create_preview(transaction)

    preview = transaction.previews[preview_id]
    snapshot = transaction.candidate_snapshots[preview.candidate_snapshot_id]

    assert preview.status is PreviewStatus.PENDING
    assert preview.actual_change_impact.name == "L2"
    assert transaction.branches[branch_id].head_revision_id == base_revision_id
    assert snapshot.candidate_content_hash == preview.candidate_content_hash
    assert len(snapshot.candidate_ir.tracks) == 1


@pytest.mark.asyncio
async def test_approve_materializes_once_and_idempotently_advances_branch() -> None:
    transaction = FakeTransaction()
    _, branch_id, base_revision_id, preview_id = await _create_preview(transaction)
    request = DecidePreviewRequest(
        preview_id=preview_id,
        decision=PreviewDecision.APPROVE,
        actor_id="user",
        idempotency_key="approve-001",
    )
    decide = DecidePreview(transaction, clock=lambda: NOW + timedelta(minutes=1))

    first = await decide(request)
    replay = await decide(request)

    assert first.status is PreviewStatus.APPROVED
    assert first.revision_id is not None
    assert replay.revision_id == first.revision_id
    assert replay.replayed is True
    assert transaction.branches[branch_id].head_revision_id == first.revision_id
    assert transaction.revisions[first.revision_id].parent_revision_id == base_revision_id
    assert len(transaction.materializations) == 1
    assert len(transaction.approvals) == 1


@pytest.mark.asyncio
async def test_reject_keeps_branch_head_and_creates_no_revision() -> None:
    transaction = FakeTransaction()
    _, branch_id, base_revision_id, preview_id = await _create_preview(transaction)

    result = await DecidePreview(transaction, clock=lambda: NOW + timedelta(minutes=1))(
        DecidePreviewRequest(
            preview_id=preview_id,
            decision=PreviewDecision.REJECT,
            actor_id="user",
            idempotency_key="reject-001",
        )
    )

    assert result.status is PreviewStatus.REJECTED
    assert result.revision_id is None
    assert transaction.branches[branch_id].head_revision_id == base_revision_id
    assert not transaction.materializations


@pytest.mark.asyncio
async def test_stale_approval_persists_superseded_then_returns_revision_conflict() -> None:
    transaction = FakeTransaction()
    project_id, branch_id, base_revision_id, preview_id = await _create_preview(transaction)
    await CommitCommandBatch(transaction)(
        CommitCommandBatchRequest(
            project_id=project_id,
            branch_id=branch_id,
            base_revision_id=base_revision_id,
            commands=(_add_track("human", name="Human Keys"),),
            actor_id="user",
            author_kind=AuthorKind.HUMAN,
            reason="TRACK_ADDED",
            idempotency_key="commit-after-preview",
        )
    )
    current_head = transaction.branches[branch_id].head_revision_id

    with pytest.raises(RevisionConflictError) as raised:
        await DecidePreview(transaction, clock=lambda: NOW + timedelta(minutes=1))(
            DecidePreviewRequest(
                preview_id=preview_id,
                decision=PreviewDecision.APPROVE,
                actor_id="user",
                idempotency_key="approve-stale",
            )
        )

    assert raised.value.current_revision_id == current_head
    assert transaction.previews[preview_id].status is PreviewStatus.SUPERSEDED
    assert not transaction.materializations


@pytest.mark.asyncio
async def test_expired_preview_is_terminal_without_materialization() -> None:
    transaction = FakeTransaction()
    _, _, _, preview_id = await _create_preview(transaction)

    with pytest.raises(ApplicationError, match="PREVIEW_EXPIRED") as raised:
        await DecidePreview(transaction, clock=lambda: NOW + timedelta(days=2))(
            DecidePreviewRequest(
                preview_id=preview_id,
                decision=PreviewDecision.APPROVE,
                actor_id="user",
                idempotency_key="approve-expired",
            )
        )

    assert raised.value.code == "PREVIEW_EXPIRED"
    assert transaction.previews[preview_id].status is PreviewStatus.EXPIRED
    assert not transaction.materializations
