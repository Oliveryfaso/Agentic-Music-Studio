from __future__ import annotations

from uuid import UUID

import pytest
from motif_forge.domain.commands import (
    AddNotesCommand,
    AddNotesPayload,
    Selection,
    SetTrackParamCommand,
    SetTrackParamPayload,
)
from motif_forge.domain.editing import (
    EditPatchProposal,
    EditVersionRefs,
    LockedRangeRef,
    simulate_edit_patch,
)
from motif_forge.domain.errors import DomainValidationError
from motif_forge.domain.ir import (
    ArrangementIR,
    NoteClip,
    NoteEvent,
    Section,
    Track,
    TrackRole,
    TrackType,
)
from motif_forge.domain.revisions import ChangeImpact


def uid(value: int) -> UUID:
    return UUID(int=value)


PROJECT_ID = uid(1)
BRANCH_ID = uid(2)
REVISION_ID = uid(3)
MELODY_TRACK_ID = uid(10)
PAD_TRACK_ID = uid(11)
CLIP_ID = uid(20)


def arrangement() -> ArrangementIR:
    return ArrangementIR(
        project_id=PROJECT_ID,
        sections=(Section(section_id=uid(4), start_tick=0, end_tick=3840, label="A"),),
        tracks=(
            Track(
                track_id=MELODY_TRACK_ID,
                track_type=TrackType.INSTRUMENT,
                name="Lead",
                role=TrackRole.MELODY,
                clips=(NoteClip(clip_id=CLIP_ID, start_tick=0, duration_tick=1920),),
            ),
            Track(
                track_id=PAD_TRACK_ID,
                track_type=TrackType.INSTRUMENT,
                name="Pad",
                role=TrackRole.HARMONY,
            ),
        ),
    )


def proposal(
    *, selection: Selection, commands: tuple[object, ...], predicted: ChangeImpact,
    locked_ranges: tuple[LockedRangeRef, ...] = (),
):
    return EditPatchProposal(
        proposal_id=uid(30),
        project_id=PROJECT_ID,
        branch_id=BRANCH_ID,
        base_revision_id=REVISION_ID,
        selection=selection,
        locked_ranges=locked_ranges,
        commands=commands,
        rationale="Apply the requested bounded change.",
        expected_effect="Only the selected material changes.",
        predicted_change_impact=predicted,
        confidence=0.9,
        versions=EditVersionRefs(prompt="edit-prompt.v1", model="fallback"),
    )


def test_simple_agent_gain_patch_is_l0_and_preserves_other_tracks() -> None:
    selection = Selection(track_ids=(PAD_TRACK_ID,), start_tick=0, end_tick=1920)
    command = SetTrackParamCommand(
        command_id=uid(31),
        actor_kind="agent",
        client_sequence=0,
        selection=selection,
        payload=SetTrackParamPayload(
            track_id=PAD_TRACK_ID, parameter="gain_db", value=-2.0
        ),
    )

    result = simulate_edit_patch(
        arrangement(), proposal(selection=selection, commands=(command,), predicted=ChangeImpact.L0)
    )

    assert result.actual_change_impact is ChangeImpact.L0
    assert result.non_target_preserved is True
    assert result.affected_track_ids == (PAD_TRACK_ID,)
    assert result.candidate_ir.tracks[0] == arrangement().tracks[0]


def test_agent_note_generation_escalates_predicted_l1_to_l2() -> None:
    selection = Selection(track_ids=(MELODY_TRACK_ID,), start_tick=0, end_tick=1920)
    command = AddNotesCommand(
        command_id=uid(32),
        actor_kind="agent",
        client_sequence=0,
        selection=selection,
        payload=AddNotesPayload(
            track_id=MELODY_TRACK_ID,
            clip_id=CLIP_ID,
            notes=(NoteEvent(note_id=uid(40), pitch=64, start_tick=0, duration_tick=480),),
        ),
    )

    result = simulate_edit_patch(
        arrangement(), proposal(selection=selection, commands=(command,), predicted=ChangeImpact.L1)
    )

    assert result.actual_change_impact is ChangeImpact.L2
    assert result.render_recommendation == "candidate_preview"


def test_command_target_outside_declared_selection_fails_closed() -> None:
    selection = Selection(track_ids=(MELODY_TRACK_ID,), start_tick=0, end_tick=1920)
    command = SetTrackParamCommand(
        command_id=uid(33),
        actor_kind="agent",
        client_sequence=0,
        selection=selection,
        payload=SetTrackParamPayload(track_id=PAD_TRACK_ID, parameter="pan", value=0.25),
    )

    with pytest.raises(DomainValidationError) as captured:
        simulate_edit_patch(
            arrangement(),
            proposal(
                selection=selection,
                commands=(command,),
                predicted=ChangeImpact.L0,
            ),
        )

    assert {item.code for item in captured.value.issues} == {"EDIT_SCOPE_VIOLATION"}


def test_command_overlapping_locked_range_fails_closed() -> None:
    selection = Selection(track_ids=(PAD_TRACK_ID,), start_tick=0, end_tick=1920)
    command = SetTrackParamCommand(
        command_id=uid(34), actor_kind="agent", client_sequence=0, selection=selection,
        payload=SetTrackParamPayload(track_id=PAD_TRACK_ID, parameter="gain_db", value=-2),
    )
    with pytest.raises(DomainValidationError) as captured:
        simulate_edit_patch(arrangement(), proposal(
            selection=selection, commands=(command,), predicted=ChangeImpact.L0,
            locked_ranges=(
                LockedRangeRef(track_id=PAD_TRACK_ID, start_tick=960, end_tick=2880),
            ),
        ))
    assert {item.code for item in captured.value.issues} == {"LOCKED_RANGE_VIOLATION"}
