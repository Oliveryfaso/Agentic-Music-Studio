"""M2 deterministic EQ persistence/projection Eval, without audio-quality claims."""

from uuid import UUID, uuid4

import pytest
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.application.undo import build_inverse_commands
from motif_forge.domain.commands import (
    Selection,
    SetPianoEqCommand,
    SetPianoEqPayload,
    apply_commands,
)
from motif_forge.domain.ir import (
    ArrangementIRV4,
    MixPianoRenderProfile,
    NoteClip,
    NoteEvent,
    PianoEqState,
    PianoMixState,
    PianoTrackEq,
    PianoTrackMix,
    Section,
    Track,
    TrackType,
)


def test_eq_snapshot_and_bypass_preserve_score_and_mix_eval():
    ids = (UUID(int=1), UUID(int=2))
    base = ArrangementIRV4(
        project_id=uuid4(),
        render_profile=MixPianoRenderProfile(),
        sections=(Section(section_id=uuid4(), start_tick=0, end_tick=3840, label="EQ eval"),),
        tracks=tuple(
            Track(
                track_id=identity,
                track_type=TrackType.INSTRUMENT,
                name="piano",
                instrument_ref="builtin:jazz-piano",
                clips=(
                    NoteClip(
                        clip_id=uuid4(),
                        start_tick=0,
                        duration_tick=3840,
                        notes=(
                            NoteEvent(note_id=uuid4(), pitch=60, start_tick=0, duration_tick=480),
                        ),
                    ),
                ),
            )
            for identity in ids
        ),
        piano_mix=PianoMixState(
            tracks=tuple(PianoTrackMix(track_id=identity, mute=True) for identity in ids)
        ),
    )
    state = PianoEqState(
        tracks=tuple(
            PianoTrackEq(
                track_id=identity, bypass=True, low_gain_db=6.0, mid_gain_db=-4.0, high_gain_db=3.0
            )
            for identity in ids
        )
    )
    action = SetPianoEqCommand(
        command_id=uuid4(),
        client_sequence=0,
        selection=Selection(track_ids=ids),
        payload=SetPianoEqPayload(eq=state),
    )
    value = apply_commands(base, (action,))
    assert value.tracks == base.tracks and value.piano_mix == base.piano_mix, (
        "PIANO_EQ_SOURCE_CHANGED"
    )
    graph = compile_audio_graph(value).graph
    assert graph["expectedSilence"], "PIANO_EQ_MIX_AUDIBILITY_DRIFT"
    assert all(t["eq3"]["bypass"] and t["eq3"]["low_gain_db"] == 6.0 for t in graph["tracks"]), (
        "PIANO_EQ_BYPASS_LOST_SETTINGS"
    )
    assert (
        apply_commands(
            value, build_inverse_commands(base, value, (action,), actor_id="human:eq-eval")
        )
        == base
    ), "PIANO_EQ_UNDO_DRIFT"


def test_eq_rejects_duplicate_target_eval():
    with pytest.raises(ValueError, match="PIANO_EQ_TRACKS_INVALID"):
        PianoEqState(tracks=(PianoTrackEq(track_id=UUID(int=1)),) * 2)
