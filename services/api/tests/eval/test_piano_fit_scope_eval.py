"""Structural scope Eval only; synthetic accompaniment is not a musical-quality win."""

import json
from uuid import uuid4

import pytest
from motif_forge.application.classical_import import reviewed_score
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import (
    AgentAppendPianoTrackCommand,
    AppendPianoTrackPayload,
    apply_commands,
)
from motif_forge.domain.piano_fit import piano_fit_context
from motif_forge.domain.piano_plan import compile_piano_plan, read_piano_plan
from motif_forge.domain.piano_requests import PianoSemanticRequestV2, require_semantic_source
from pydantic import ValidationError

CASES = [
    ("c01-minuet-g-a16.v1", 3, 16, "G"),
    ("c02-la-candeur-a8.v1", 4, 8, "C"),
    ("j01-bethena-a-first8.v1", 3, 8, "G"),
]


def source(score):
    p = uuid4()
    _, xml = reviewed_score(score)
    return score_to_arrangement(
        parse_musicxml(xml, namespace=p), project_id=p, source_ref="score:" + score
    )


def plan(beats, start, end, chord, dense=False):
    return read_piano_plan(
        json.dumps(
            {
                "schema_version": "accompaniment-plan.v2",
                "beats_per_bar": beats,
                "summary": "offline scope fixture, not quality",
                "bars": [
                    {
                        "bar": i,
                        "chord": chord,
                        "octave": 2,
                        "grid": list(range(0, beats * 4, 2)) if dense else [0],
                        "velocity": 48,
                        "gate_steps": 1,
                    }
                    for i in range(start, end + 1)
                ],
            }
        )
    )


@pytest.mark.parametrize("score,beats,bars,chord", CASES)
@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_fit_scope_and_density_edits_preserve_context_and_protected_events(
    score, beats, bars, chord, position
):
    base = source(score)
    before = base.model_dump_json()
    start = {"first": 1, "middle": 3, "last": bars - 3}[position]
    end = start + 3
    context = piano_fit_context(base, start_bar=start, end_bar=end)
    assert context["pulse_steps"] == list(range(0, beats * 4, 4))
    assert [b for b, _ in context["bar_candidates"]] == list(range(start, end + 1))
    assert all(start <= b <= end for b, _ in context["source_anchors"] + context["cadences"])
    assert (context["terminal_rest_start_step"] == 12) == (
        score.startswith("c02") and position == "last"
    )
    locked = piano_fit_context(base, start_bar=start, end_bar=end, include_harmony=False)
    assert locked["bar_candidates"] == locked["source_anchors"] == locked["cadences"] == []
    full = compile_piano_plan(
        base, plan(beats, 1, bars, chord, True), request_id=uuid4(), end_bar=bars
    )
    saved = apply_commands(
        base,
        (
            AgentAppendPianoTrackCommand(
                command_id=uuid4(), client_sequence=0, payload=AppendPianoTrackPayload(track=full)
            ),
        ),
    )
    changed = compile_piano_plan(
        saved,
        plan(beats, start, end, chord),
        request_id=uuid4(),
        target_track_id=full.track_id,
        start_bar=start,
        end_bar=end,
    )
    a, b = (start - 1) * beats * 480, end * beats * 480

    def outside(t):
        return tuple(n for n in t.clips[0].notes if not a <= n.start_tick < b)

    assert outside(changed) == outside(full)
    assert len([n for n in changed.clips[0].notes if a <= n.start_tick < b]) == 4
    assert all(n.start_tick + n.duration_tick <= bars * beats * 480 for n in changed.clips[0].notes)
    assert base.model_dump_json() == before


@pytest.mark.parametrize("score,beats,bars,chord", CASES)
@pytest.mark.parametrize("failure", ["meter", "gate", "coverage", "cross_boundary"])
def test_scope_failure_labels_remain_fail_closed(score, beats, bars, chord, failure):
    base = source(score)
    if failure == "meter":
        with pytest.raises(ValidationError, match="PIANO_SOURCE_MISMATCH"):
            PianoSemanticRequestV2(
                source_score_id=score,
                beats_per_bar=7 - beats,
                mode="append",
                end_bar=bars,
                intent="offline",
            )
    elif failure == "gate":
        v = plan(beats, 1, bars, chord).model_dump(mode="json")
        v["bars"][0].update(grid=[beats * 4 - 1], gate_steps=2)
        with pytest.raises(ValidationError, match="ACCOMPANIMENT_NOTE_OUT_OF_BAR"):
            read_piano_plan(json.dumps(v))
    elif failure == "coverage":
        with pytest.raises(ValueError, match="ACCOMPANIMENT_BAR_COVERAGE"):
            compile_piano_plan(
                base, plan(beats, 1, bars - 1, chord), request_id=uuid4(), end_bar=bars
            )
    else:
        track = compile_piano_plan(
            base, plan(beats, 1, bars, chord), request_id=uuid4(), end_bar=bars
        )
        # Deliberate fixture with one sustained note crossing the proposed selection boundary.
        first = track.clips[0].notes[0].model_copy(update={"duration_tick": beats * 480 + 120})
        clip = track.clips[0].model_copy(update={"notes": (first, *track.clips[0].notes[1:])})
        track = track.model_copy(update={"clips": (clip,)})
        saved = apply_commands(
            base,
            (
                AgentAppendPianoTrackCommand(
                    command_id=uuid4(),
                    client_sequence=0,
                    payload=AppendPianoTrackPayload(track=track),
                ),
            ),
        )
        with pytest.raises(ValueError, match="ACCOMPANIMENT_SCOPE_INVALID"):
            compile_piano_plan(
                saved,
                plan(beats, 1, 1, chord),
                request_id=uuid4(),
                target_track_id=track.track_id,
                start_bar=1,
                end_bar=1,
            )


@pytest.mark.parametrize("score,beats,bars,chord", CASES)
def test_performance_override_on_replaced_notes_is_not_silently_discarded(
    score, beats, bars, chord
):
    from motif_forge.domain.ir import NotePerformance, PerformancePlan

    base = source(score)
    track = compile_piano_plan(base, plan(beats, 1, bars, chord), request_id=uuid4(), end_bar=bars)
    saved = apply_commands(
        base,
        (
            AgentAppendPianoTrackCommand(
                command_id=uuid4(), client_sequence=0, payload=AppendPianoTrackPayload(track=track)
            ),
        ),
    )
    override = NotePerformance(
        track_id=track.track_id,
        clip_id=track.clips[0].clip_id,
        note_id=track.clips[0].notes[0].note_id,
        velocity_override=40,
    )
    performed = saved.model_copy(update={"performance_plan": PerformancePlan(notes=(override,))})
    with pytest.raises(ValueError, match="ACCOMPANIMENT_PERFORMANCE_CONFLICT"):
        compile_piano_plan(
            performed,
            plan(beats, 1, 1, chord),
            request_id=uuid4(),
            target_track_id=track.track_id,
            start_bar=1,
            end_bar=1,
        )


def test_valid_request_for_a_different_reviewed_score_cannot_relabel_the_source():
    request = PianoSemanticRequestV2(
        source_score_id="j01-bethena-a-first8.v1",
        beats_per_bar=3,
        mode="append",
        end_bar=8,
        intent="offline wrong source",
    )
    with pytest.raises(ValueError, match="PIANO_SOURCE_MISMATCH"):
        require_semantic_source(source("c01-minuet-g-a16.v1"), request)
