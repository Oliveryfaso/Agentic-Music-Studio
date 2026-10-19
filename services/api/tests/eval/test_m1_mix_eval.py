"""M1 deterministic mix Eval; no realtime, audio-quality or model score claim."""

from uuid import UUID, uuid4

import pytest
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.domain.commands import (
    Selection,
    SetPianoMixCommand,
    SetPianoMixPayload,
    apply_commands,
)
from motif_forge.domain.ir import (
    ArrangementIRV3,
    EnsemblePianoRenderProfile,
    NoteClip,
    NoteEvent,
    PianoMixState,
    PianoTrackMix,
    Section,
    Track,
    TrackType,
)


def test_solo_mute_and_export_scope_eval():
    ids = (UUID(int=1), UUID(int=2))
    base = ArrangementIRV3(
        project_id=uuid4(),
        render_profile=EnsemblePianoRenderProfile(),
        sections=(Section(section_id=uuid4(), start_tick=0, end_tick=3840, label="test"),),
        tracks=tuple(
            Track(
                track_id=identity,
                track_type=TrackType.INSTRUMENT,
                name="test",
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
    )
    mix = PianoMixState(
        tracks=(
            PianoTrackMix(track_id=ids[0], solo=True, mute=True),
            PianoTrackMix(track_id=ids[1]),
        )
    )
    command = SetPianoMixCommand(
        command_id=uuid4(),
        client_sequence=0,
        selection=Selection(track_ids=ids),
        payload=SetPianoMixPayload(mix=mix),
    )
    result = apply_commands(base, (command,))
    assert result.tracks == base.tracks, "PIANO_MIX_SCORE_CHANGED"
    assert compile_audio_graph(result).graph["expectedSilence"], "PIANO_MIX_MUTE_PRIORITY"
    assert compile_audio_graph(result, render_track_ids=(ids[1],)).graph["expectedSilence"], (
        "PIANO_MIX_STEM_SOLO_DRIFT"
    )


def test_mix_rejects_unknown_target_eval():
    with pytest.raises(ValueError, match="PIANO_MIX_TRACKS_INVALID"):
        PianoMixState(
            tracks=(PianoTrackMix(track_id=UUID(int=1)), PianoTrackMix(track_id=UUID(int=1)))
        )
