import json
from uuid import UUID

import pytest
from motif_forge.application.classical_import import reviewed_score
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import (
    AgentAppendPianoTrackCommand,
    AppendPianoTrackPayload,
    ReplacePianoRangeCommand,
    ReplacePianoRangePayload,
    Selection,
    apply_commands,
)
from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan
from motif_forge.providers.piano import PianoPlanProposal
from pydantic import ValidationError

CASES = [
    ("c01-minuet-g-a16.v1", 3, 16, "G"),
    ("c02-la-candeur-a8.v1", 4, 8, "C"),
    ("j01-bethena-a-first8.v1", 3, 8, "G"),
]


def source(score):
    _, xml = reviewed_score(score)
    return score_to_arrangement(
        parse_musicxml(xml, namespace=UUID(int=320)),
        project_id=UUID(int=320),
        source_ref="score:" + score,
    )


def plan(beats, bars, chord="G", start=1, grid=None, velocity=54):
    data = {
        "schema_version": "accompaniment-plan.v2",
        "beats_per_bar": beats,
        "summary": "低音区疏密变化",
        "bars": [
            {
                "bar": i,
                "chord": chord,
                "grid": list(grid if grid is not None else range(0, beats * 4, 4)),
                "octave": 2,
                "velocity": velocity,
                "gate_steps": 3,
            }
            for i in range(start, bars + 1)
        ],
    }
    return PianoPlanProposal.model_validate_json(
        json.dumps({"supported": True, "reason": "支持", "plan": data}), strict=True
    ).plan


@pytest.mark.parametrize("score,beats,bars,chord", CASES)
def test_v2_append_and_local_command_preserve_source_and_actual_bar_ticks(
    score, beats, bars, chord
):
    base = source(score)
    before = arrangement_content_hash(base)
    full = plan(beats, bars, chord)
    track = compile_piano_plan(base, full, request_id=UUID(int=321), end_bar=bars)
    assert [n.start_tick for n in track.clips[0].notes] == list(range(0, bars * beats * 480, 480))
    assert max(n.start_tick + n.duration_tick for n in track.clips[0].notes) <= bars * beats * 480
    assert arrangement_content_hash(base) == before
    cmd = AgentAppendPianoTrackCommand(
        command_id=UUID(int=322), client_sequence=0, payload=AppendPianoTrackPayload(track=track)
    )
    saved = apply_commands(base, (cmd,))
    last = min(bars, 8)
    first = last - 3
    a = (first - 1) * beats * 480
    b = last * beats * 480
    replacement = compile_piano_plan(
        saved,
        plan(beats, last, chord, start=first, grid=(0,), velocity=36),
        request_id=UUID(int=323),
        target_track_id=track.track_id,
        start_bar=first,
        end_bar=last,
    )
    change = ReplacePianoRangeCommand(
        command_id=UUID(int=324),
        client_sequence=0,
        actor_kind="agent",
        selection=Selection(track_ids=(track.track_id,), start_tick=a, end_tick=b),
        payload=ReplacePianoRangePayload(track=replacement, start_bar=first, end_bar=last),
    )
    changed = apply_commands(saved, (change,))

    def outside(t):
        return tuple(n for n in t.clips[0].notes if not a <= n.start_tick < b)

    assert changed.tracks[0] == base.tracks[0]
    assert outside(changed.tracks[1]) == outside(saved.tracks[1])
    assert len([n for n in changed.tracks[1].clips[0].notes if a <= n.start_tick < b]) == 4


def test_three_four_gate_cannot_cross_step_twelve_or_use_step_twelve():
    for grid in [(10,), (12,)]:
        with pytest.raises(ValidationError, match="ACCOMPANIMENT_NOTE_OUT_OF_BAR"):
            plan(3, 1, grid=grid)
    assert plan(3, 1, grid=(9,))


def test_c_major_f_dm_and_no_sevenths_or_wrong_key_chords():
    base = source("c02-la-candeur-a8.v1")
    for chord in ["F", "Dm"]:
        track = compile_piano_plan(base, plan(4, 8, chord), request_id=UUID(int=330), end_bar=8)
        assert track.clips[0].notes[0].pitch == ({"F": 41, "Dm": 38}[chord])
    with pytest.raises(ValueError, match="ACCOMPANIMENT_CHORD_UNSUPPORTED"):
        compile_piano_plan(base, plan(4, 8, "Bm"), request_id=UUID(int=330), end_bar=8)
    with pytest.raises(ValidationError):
        plan(4, 8, "G7/B")


@pytest.mark.parametrize("score,beats,bars,chord", CASES)
def test_new_source_rejects_legacy_plan_wrong_meter_and_tail_bar(score, beats, bars, chord):
    base = source(score)
    legacy = AccompanimentPlan(
        summary="旧计划",
        bars=tuple(
            BarPlan(bar=i, chord="G", grid=(0,), octave=2, velocity=54) for i in range(1, bars + 1)
        ),
    )
    with pytest.raises(ValueError, match="ACCOMPANIMENT_PLAN_VERSION_MISMATCH"):
        compile_piano_plan(base, legacy, request_id=UUID(int=331), end_bar=bars)
    with pytest.raises(ValueError, match="ACCOMPANIMENT_METER_MISMATCH"):
        compile_piano_plan(
            base, plan(7 - beats, bars, chord), request_id=UUID(int=331), end_bar=bars
        )
    with pytest.raises(ValueError, match="ACCOMPANIMENT_SCOPE_INVALID"):
        compile_piano_plan(
            base, plan(beats, bars, chord), request_id=UUID(int=331), end_bar=bars + 1
        )
