from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from motif_forge.application.errors import RevisionConflictError
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.application.undo import UndoCommittedRevision, UndoCommittedRevisionRequest
from motif_forge.domain.commands import (
    AddTrackCommand,
    AddTrackPayload,
    MoveClipCommand,
    MoveClipPayload,
    Selection,
)
from motif_forge.domain.ir import NoteClip, Section, Track, TrackRole, TrackType
from motif_forge.domain.revisions import AuthorKind

from .fakes import FakeTransaction


async def _committed_move(
    transaction: FakeTransaction,
) -> tuple[UUID, UUID, UUID, UUID]:
    root = await CreateProject(transaction)(
        CreateProjectRequest(name="Undo", actor_id="local-user", idempotency_key="create-undo")
    )
    root_revision = transaction.revisions[root.root_revision_id]
    transaction.revisions[root.root_revision_id] = root_revision.model_copy(
        update={
            "arrangement_ir": root_revision.arrangement_ir.model_copy(
                update={
                    "sections": (
                        Section(section_id=uuid4(), start_tick=0, end_tick=3840, label="A"),
                    )
                }
            )
        }
    )
    track_id, clip_id = uuid4(), uuid4()
    seed = await CommitCommandBatch(transaction)(
        CommitCommandBatchRequest(
            project_id=root.project_id,
            branch_id=root.active_branch_id,
            base_revision_id=root.root_revision_id,
            commands=(
                AddTrackCommand(
                    command_id=uuid4(),
                    actor_kind="human",
                    client_sequence=0,
                    payload=AddTrackPayload(
                        track=Track(
                            track_id=track_id,
                            track_type=TrackType.INSTRUMENT,
                            name="Lead",
                            role=TrackRole.MELODY,
                            clips=(NoteClip(clip_id=clip_id, start_tick=0, duration_tick=960),),
                        )
                    ),
                ),
            ),
            actor_id="local-user",
            author_kind=AuthorKind.HUMAN,
            reason="SEED",
            idempotency_key="seed-undo",
        )
    )
    moved = await CommitCommandBatch(transaction)(
        CommitCommandBatchRequest(
            project_id=root.project_id,
            branch_id=root.active_branch_id,
            base_revision_id=seed.revision_id,
            commands=(
                MoveClipCommand(
                    command_id=uuid4(),
                    actor_kind="human",
                    client_sequence=0,
                    selection=Selection(track_ids=(track_id,), start_tick=0, end_tick=1920),
                    payload=MoveClipPayload(track_id=track_id, clip_id=clip_id, start_tick=960),
                ),
            ),
            actor_id="local-user",
            author_kind=AuthorKind.HUMAN,
            reason="MOVE",
            idempotency_key="move-undo",
        )
    )
    return root.project_id, root.active_branch_id, seed.revision_id, moved.revision_id


@pytest.mark.asyncio
async def test_undo_move_creates_new_inverse_revision_and_replays() -> None:
    transaction = FakeTransaction()
    project_id, branch_id, seed_id, moved_id = await _committed_move(transaction)
    request = UndoCommittedRevisionRequest(
        project_id=project_id,
        branch_id=branch_id,
        base_revision_id=moved_id,
        target_revision_id=moved_id,
        actor_id="local-user",
        idempotency_key="undo-move-001",
    )
    undo = UndoCommittedRevision(transaction)

    result = await undo(request)
    replay = await undo(request)

    assert result.revision_id != moved_id
    assert replay.revision_id == result.revision_id
    assert replay.replayed is True
    assert transaction.branches[branch_id].head_revision_id == result.revision_id
    assert (
        transaction.revisions[result.revision_id].arrangement_ir
        == transaction.revisions[seed_id].arrangement_ir
    )
    assert len(transaction.command_batches) == 3


@pytest.mark.asyncio
async def test_undo_refuses_stale_branch_head_and_preserves_history() -> None:
    transaction = FakeTransaction()
    project_id, branch_id, seed_id, moved_id = await _committed_move(transaction)

    with pytest.raises(RevisionConflictError):
        await UndoCommittedRevision(transaction)(
            UndoCommittedRevisionRequest(
                project_id=project_id,
                branch_id=branch_id,
                base_revision_id=seed_id,
                target_revision_id=moved_id,
                actor_id="local-user",
                idempotency_key="undo-stale-001",
            )
        )

    assert len(transaction.command_batches) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "score,beats,bars,chord",
    [
        ("c01-minuet-g-a16.v1", 3, 16, "G"),
        ("c02-la-candeur-a8.v1", 4, 8, "F"),
        ("j01-bethena-a-first8.v1", 3, 8, "G"),
    ],
)
async def test_undo_approved_semantic_piano_append_restores_exact_import(
    score, beats, bars, chord
) -> None:
    import json

    from motif_forge.application.classical_import import reviewed_score
    from motif_forge.application.previews import (
        CreateCommandPreview,
        CreateCommandPreviewRequest,
        DecidePreview,
        DecidePreviewRequest,
        PreviewDecision,
    )
    from motif_forge.domain.canonical import arrangement_content_hash
    from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
    from motif_forge.domain.commands import (
        AgentAppendPianoTrackCommand,
        AppendPianoTrackPayload,
    )
    from motif_forge.domain.piano_plan import compile_piano_plan, read_piano_plan
    from motif_forge.domain.revisions import versions_for_arrangement

    transaction = FakeTransaction()
    root = await CreateProject(transaction)(
        CreateProjectRequest(name="Semantic Undo", actor_id="human", idempotency_key="root-undo")
    )
    _, xml = reviewed_score(score)
    original = score_to_arrangement(
        parse_musicxml(xml, namespace=root.project_id),
        project_id=root.project_id,
        source_ref="score:" + score,
    )
    transaction.revisions[root.root_revision_id] = transaction.revisions[
        root.root_revision_id
    ].model_copy(
        update={
            "arrangement_ir": original,
            "content_hash": arrangement_content_hash(original),
            "versions": versions_for_arrangement(original),
        }
    )
    plan = read_piano_plan(
        json.dumps(
            {
                "schema_version": "accompaniment-plan.v2",
                "beats_per_bar": beats,
                "summary": "deterministic regression, no model",
                "bars": [
                    {
                        "bar": i,
                        "chord": chord,
                        "grid": [0],
                        "octave": 2,
                        "velocity": 48,
                        "gate_steps": 3,
                    }
                    for i in range(1, bars + 1)
                ],
            }
        )
    )
    track = compile_piano_plan(original, plan, request_id=uuid4(), end_bar=bars)
    preview = await CreateCommandPreview(transaction)(
        CreateCommandPreviewRequest(
            project_id=root.project_id,
            branch_id=root.active_branch_id,
            base_revision_id=root.root_revision_id,
            candidate_id=uuid4(),
            commands=(
                AgentAppendPianoTrackCommand(
                    command_id=uuid4(),
                    client_sequence=1,
                    payload=AppendPianoTrackPayload(track=track),
                ),
            ),
            actor_id="agent:regression",
            idempotency_key="preview-undo",
        )
    )
    kept = await DecidePreview(transaction)(
        DecidePreviewRequest(
            preview_id=preview.preview_id,
            decision=PreviewDecision.APPROVE,
            actor_id="human",
            approval_assertion="Approve this exact owned regression candidate.",
            idempotency_key="keep-undo",
        )
    )
    # Fake materialization stores snapshots; mirror the PG command lookup contract.
    transaction.command_batches.append(
        (
            transaction.revisions[kept.revision_id],
            transaction.candidate_snapshots[preview.candidate_snapshot_id].commands,
        )
    )
    request = UndoCommittedRevisionRequest(
        project_id=root.project_id,
        branch_id=root.active_branch_id,
        base_revision_id=kept.revision_id,
        target_revision_id=kept.revision_id,
        actor_id="human",
        idempotency_key="undo-semantic-append",
    )
    undo = UndoCommittedRevision(transaction)
    result = await undo(request)
    assert (await undo(request)).revision_id == result.revision_id
    restored = transaction.revisions[result.revision_id]
    assert restored.arrangement_ir == original
    assert restored.content_hash == arrangement_content_hash(original)
    assert transaction.branches[root.active_branch_id].head_revision_id == result.revision_id
