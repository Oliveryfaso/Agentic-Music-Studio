from uuid import UUID, uuid4

import pytest
from motif_forge.application.edit_decisions import (
    ApplyEditPreviewDecision,
    AttachEditPreviewArtifact,
    AutoCommitEdit,
    CreateEditPreview,
    EditPreviewDecision,
)
from motif_forge.application.errors import ApplicationError
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.domain.commands import (
    AddTrackCommand,
    AddTrackPayload,
    Selection,
    SetTrackParamCommand,
    SetTrackParamPayload,
)
from motif_forge.domain.editing import EditPatchProposal, EditVersionRefs
from motif_forge.domain.ir import Track, TrackRole, TrackType
from motif_forge.domain.revisions import AuthorKind, ChangeImpact

from .fakes import FakeTransaction


async def seeded() -> tuple[FakeTransaction, object, object, object]:
    transaction = FakeTransaction()
    root = await CreateProject(transaction)(
        CreateProjectRequest(name="Edit", actor_id="human", idempotency_key="edit-root")
    )
    track_id = uuid4()
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
                            name="Pad",
                            role=TrackRole.HARMONY,
                        )
                    ),
                ),
            ),
            actor_id="human",
            author_kind=AuthorKind.HUMAN,
            reason="SEED",
            idempotency_key="edit-seed",
        )
    )
    return transaction, root, seed, track_id


def proposal(
    root: object, seed: object, command: object, impact: ChangeImpact
) -> EditPatchProposal:
    track_id = (
        command.payload.track_id
        if hasattr(command.payload, "track_id")
        else command.payload.track.track_id
    )
    return EditPatchProposal(
        proposal_id=uuid4(),
        project_id=root.project_id,
        branch_id=root.active_branch_id,
        base_revision_id=seed.revision_id,
        selection=Selection(track_ids=(track_id,)),
        commands=(command,),
        rationale="bounded edit",
        expected_effect="audible local change",
        predicted_change_impact=impact,
        confidence=1,
        versions=EditVersionRefs(prompt="test", model="fake"),
    )


@pytest.mark.asyncio
async def test_l0_edit_auto_commits_once() -> None:
    transaction, root, seed, track_id = await seeded()
    command = SetTrackParamCommand(
        command_id=uuid4(),
        actor_kind="agent",
        client_sequence=0,
        payload=SetTrackParamPayload(track_id=track_id, parameter="gain_db", value=-2.0),
    )
    edit = proposal(root, seed, command, ChangeImpact.L0)
    handler = AutoCommitEdit(transaction, run_id=uuid4())
    first = await handler(edit, {}, {})
    assert first["materialized_revision_id"] == str(
        transaction.branches[root.active_branch_id].head_revision_id
    )
    assert len(transaction.command_batches) == 2


@pytest.mark.asyncio
async def test_preview_approval_requires_real_artifact() -> None:
    transaction, root, seed, _track_id = await seeded()
    new_track = AddTrackCommand(
        command_id=uuid4(),
        actor_kind="agent",
        client_sequence=0,
        payload=AddTrackPayload(
            track=Track(
                track_id=uuid4(),
                track_type=TrackType.INSTRUMENT,
                name="Counterline",
                role=TrackRole.MELODY,
            )
        ),
    )
    edit = proposal(root, seed, new_track, ChangeImpact.L2)
    run_id = uuid4()
    waiting = await CreateEditPreview(transaction, run_id=run_id)(edit, {}, {})
    assert transaction.branches[root.active_branch_id].head_revision_id == seed.revision_id
    decision = EditPreviewDecision(
        action="approve",
        preview_id=UUID(str(waiting["pending_preview_id"])),
        expected_candidate_content_hash=str(waiting["candidate_content_hash"]),
        actor_id="human",
        approval_assertion="I approve this rendered edit.",
    )
    with pytest.raises(ApplicationError) as captured:
        await ApplyEditPreviewDecision(transaction, run_id=run_id)(decision)
    assert captured.value.code == "EDIT_PREVIEW_ARTIFACT_REQUIRED"


@pytest.mark.asyncio
async def test_rendered_artifact_is_attached_once_before_approval() -> None:
    transaction, root, seed, _track_id = await seeded()
    new_track = AddTrackCommand(
        command_id=uuid4(),
        actor_kind="agent",
        client_sequence=0,
        payload=AddTrackPayload(
            track=Track(
                track_id=uuid4(),
                track_type=TrackType.INSTRUMENT,
                name="Counterline",
                role=TrackRole.MELODY,
            )
        ),
    )
    edit = proposal(root, seed, new_track, ChangeImpact.L2)
    waiting = await CreateEditPreview(transaction, run_id=uuid4())(edit, {}, {})
    preview_id = UUID(str(waiting["pending_preview_id"]))
    artifact_id = uuid4()

    attach = AttachEditPreviewArtifact(transaction)
    first = await attach(
        preview_id=preview_id,
        candidate_snapshot_id=UUID(str(waiting["candidate_snapshot_id"])),
        expected_candidate_content_hash=str(waiting["candidate_content_hash"]),
        preview_artifact_id=artifact_id,
    )
    replay = await attach(
        preview_id=preview_id,
        candidate_snapshot_id=UUID(str(waiting["candidate_snapshot_id"])),
        expected_candidate_content_hash=str(waiting["candidate_content_hash"]),
        preview_artifact_id=artifact_id,
    )

    assert first.preview_artifact_ids == (artifact_id,)
    assert replay.preview_artifact_ids == (artifact_id,)
    assert transaction.previews[preview_id].preview_artifact_ids == (artifact_id,)

    with pytest.raises(ApplicationError) as captured:
        await attach(
            preview_id=preview_id,
            candidate_snapshot_id=UUID(str(waiting["candidate_snapshot_id"])),
            expected_candidate_content_hash=str(waiting["candidate_content_hash"]),
            preview_artifact_id=uuid4(),
        )
    assert captured.value.code == "EDIT_PREVIEW_ARTIFACT_CONFLICT"
