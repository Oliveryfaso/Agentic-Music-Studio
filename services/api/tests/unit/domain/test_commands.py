from __future__ import annotations

from uuid import UUID

import pytest
from motif_forge.domain import (
    AddClipCommand,
    AddClipPayload,
    AddNotesCommand,
    AddNotesPayload,
    AddTrackCommand,
    AddTrackPayload,
    ArrangementIR,
    ClipTargetPayload,
    DeleteClipCommand,
    DeleteNotesCommand,
    DeleteNotesPayload,
    DomainValidationError,
    ImportAudioCommand,
    ImportAudioPayload,
    LockedRange,
    MoveClipCommand,
    MoveClipPayload,
    NoteClip,
    NoteEvent,
    NoteUpdate,
    Section,
    SetClipParamCommand,
    SetClipParamPayload,
    SplitClipCommand,
    SplitClipPayload,
    Track,
    TrackRole,
    TrackType,
    TrimClipCommand,
    TrimClipPayload,
    UpdateNotesCommand,
    UpdateNotesPayload,
    apply_command,
    apply_commands,
    create_empty_arrangement,
    validate_command,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


def command_fields(sequence: int) -> dict[str, object]:
    return {
        "command_id": uid(100 + sequence),
        "actor_kind": "human",
        "client_sequence": sequence,
    }


def bounded_empty_arrangement() -> ArrangementIR:
    return ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=3_840, label="A"),),
    )


def instrument_track(*, locked: bool = False) -> Track:
    return Track(
        track_id=uid(10),
        track_type=TrackType.INSTRUMENT,
        name="Lead",
        role=TrackRole.MELODY,
        locked_ranges=(LockedRange(start_tick=0, end_tick=480),) if locked else (),
    )


def test_command_batch_builds_track_clip_and_notes_without_mutating_base() -> None:
    base = bounded_empty_arrangement()
    track = instrument_track()
    clip = NoteClip(clip_id=uid(20), start_tick=0, duration_tick=1_920)
    note = NoteEvent(note_id=uid(30), pitch=60, start_tick=0, duration_tick=480)

    result = apply_commands(
        base,
        (
            AddTrackCommand(payload=AddTrackPayload(track=track), **command_fields(0)),
            AddClipCommand(
                payload=AddClipPayload(track_id=track.track_id, clip=clip),
                **command_fields(1),
            ),
            AddNotesCommand(
                payload=AddNotesPayload(
                    track_id=track.track_id,
                    clip_id=clip.clip_id,
                    notes=(note,),
                ),
                **command_fields(2),
            ),
        ),
    )

    assert base.tracks == ()
    assert result.tracks[0].clips[0].notes == (note,)  # type: ignore[union-attr]


def test_import_audio_atomically_creates_bounded_section_track_and_clip() -> None:
    base = create_empty_arrangement(uid(1))
    result = apply_command(
        base,
        ImportAudioCommand(
            payload=ImportAudioPayload(
                track_id=uid(10),
                clip_id=uid(20),
                section_id=uid(30),
                artifact_id=uid(40),
                track_name="Imported Texture",
                duration_tick=2_001,
                source_duration_seconds=2.084,
            ),
            **command_fields(0),
        ),
    )

    assert result.duration_tick == 3_840
    assert result.tracks[0].track_type is TrackType.AUDIO
    clip = result.tracks[0].clips[0]
    assert clip.artifact_id == uid(40)  # type: ignore[union-attr]
    assert clip.duration_tick == 2_001


def test_move_trim_split_and_clip_parameter_commands() -> None:
    note = NoteEvent(note_id=uid(30), pitch=64, start_tick=240, duration_tick=960)
    clip = NoteClip(
        clip_id=uid(20),
        start_tick=0,
        duration_tick=1_920,
        notes=(note,),
    )
    base = ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=5_760, label="A"),),
        tracks=(instrument_track().model_copy(update={"clips": (clip,)}),),
    )

    moved = apply_command(
        base,
        MoveClipCommand(
            payload=MoveClipPayload(track_id=uid(10), clip_id=uid(20), start_tick=1_920),
            **command_fields(0),
        ),
    )
    trimmed = apply_command(
        moved,
        TrimClipCommand(
            payload=TrimClipPayload(
                track_id=uid(10),
                clip_id=uid(20),
                start_tick=2_160,
                end_tick=3_360,
            ),
            **command_fields(1),
        ),
    )
    split = apply_command(
        trimmed,
        SplitClipCommand(
            payload=SplitClipPayload(
                track_id=uid(10),
                clip_id=uid(20),
                split_tick=2_640,
                right_clip_id=uid(21),
            ),
            **command_fields(2),
        ),
    )
    changed = apply_command(
        split,
        SetClipParamCommand(
            payload=SetClipParamPayload(
                track_id=uid(10), clip_id=uid(21), parameter="gain_db", value=-3.0
            ),
            **command_fields(3),
        ),
    )

    left, right = changed.tracks[0].clips
    assert (left.start_tick, left.duration_tick) == (2_160, 480)
    assert (right.start_tick, right.duration_tick, right.gain_db) == (2_640, 720, -3.0)


def test_update_delete_notes_and_delete_clip() -> None:
    notes = (
        NoteEvent(note_id=uid(30), pitch=60, start_tick=0, duration_tick=240),
        NoteEvent(note_id=uid(31), pitch=62, start_tick=240, duration_tick=240),
    )
    clip = NoteClip(clip_id=uid(20), start_tick=0, duration_tick=960, notes=notes)
    base = ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=1_920, label="A"),),
        tracks=(instrument_track().model_copy(update={"clips": (clip,)}),),
    )
    updated = apply_command(
        base,
        UpdateNotesCommand(
            payload=UpdateNotesPayload(
                track_id=uid(10),
                clip_id=uid(20),
                updates=(NoteUpdate(note_id=uid(30), pitch=67),),
            ),
            **command_fields(0),
        ),
    )
    deleted_note = apply_command(
        updated,
        DeleteNotesCommand(
            payload=DeleteNotesPayload(track_id=uid(10), clip_id=uid(20), note_ids=(uid(31),)),
            **command_fields(1),
        ),
    )
    deleted_clip = apply_command(
        deleted_note,
        DeleteClipCommand(
            payload=ClipTargetPayload(track_id=uid(10), clip_id=uid(20)),
            **command_fields(2),
        ),
    )

    remaining_clip = deleted_note.tracks[0].clips[0]
    assert isinstance(remaining_clip, NoteClip)
    assert [(note.note_id, note.pitch) for note in remaining_clip.notes] == [(uid(30), 67)]
    assert deleted_clip.tracks[0].clips == ()


def test_invalid_and_locked_commands_return_stable_issues() -> None:
    empty = create_empty_arrangement(uid(1))
    missing = MoveClipCommand(
        payload=MoveClipPayload(track_id=uid(10), clip_id=uid(20), start_tick=0),
        **command_fields(0),
    )
    assert validate_command(empty, missing)[0].code == "TRACK_NOT_FOUND"

    clip = NoteClip(clip_id=uid(20), start_tick=0, duration_tick=960)
    locked = ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=1_920, label="A"),),
        tracks=(instrument_track(locked=True).model_copy(update={"clips": (clip,)}),),
    )
    with pytest.raises(DomainValidationError) as exc_info:
        apply_command(
            locked,
            DeleteClipCommand(
                payload=ClipTargetPayload(track_id=uid(10), clip_id=uid(20)),
                **command_fields(1),
            ),
        )
    assert exc_info.value.issues[0].code == "LOCKED_RANGE_VIOLATION"
