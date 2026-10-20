"""Offline P2.3 success / failure labels; not a paid-model or listening score."""

import json
from uuid import uuid4

import pytest
from motif_forge.application.classical_import import reviewed_score
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.piano_plan import compile_piano_plan, read_piano_plan
from pydantic import ValidationError


@pytest.mark.parametrize(
    "score,beats,bars,chord",
    [
        ("c01-minuet-g-a16.v1", 3, 16, "G"),
        ("c02-la-candeur-a8.v1", 4, 8, "F"),
        ("j01-bethena-a-first8.v1", 3, 8, "G"),
    ],
)
def test_source_aware_density_contrast_and_release_bar_locality_eval(score, beats, bars, chord):
    project = uuid4()
    _, xml = reviewed_score(score)
    base = score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref="score:" + score
    )
    value = {
        "schema_version": "accompaniment-plan.v2",
        "beats_per_bar": beats,
        "summary": "前半稀疏后半活跃",
        "bars": [
            {
                "bar": i,
                "chord": chord,
                "grid": [0] if i <= bars // 2 else list(range(0, beats * 4, 4)),
                "octave": 2,
                "velocity": 48,
                "gate_steps": 3,
            }
            for i in range(1, bars + 1)
        ],
    }
    track = compile_piano_plan(
        base, read_piano_plan(json.dumps(value)), request_id=uuid4(), end_bar=bars
    )
    notes = track.clips[0].notes
    half = bars // 2 * beats * 480
    assert sum(n.start_tick < half for n in notes) == bars // 2
    assert sum(n.start_tick >= half for n in notes) == bars // 2 * beats
    assert all(n.start_tick + n.duration_tick <= bars * beats * 480 for n in notes)
    value["beats_per_bar"] = 3
    value["bars"][0]["grid"] = [11]
    value["bars"][0]["gate_steps"] = 2
    with pytest.raises(ValidationError, match="ACCOMPANIMENT_NOTE_OUT_OF_BAR"):
        read_piano_plan(json.dumps(value))
