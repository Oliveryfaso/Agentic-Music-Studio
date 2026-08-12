from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from motif_forge.domain.composition import build_s1_composition, validate_s1_arrangement
from motif_forge.domain.ir import NoteClip, TrackRole
from motif_forge.domain.policies import compute_change_impact
from motif_forge.domain.revisions import ChangeImpact

EVAL_PATH = Path(__file__).parents[4] / "evals" / "s1_deterministic_cases.jsonl"


def _cases() -> list[dict[str, object]]:
    return [json.loads(line) for line in EVAL_PATH.read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["case_id"]))
def test_s1_deterministic_eval(case: dict[str, object]) -> None:
    seed = int(case["seed"])
    project_id = uuid5(NAMESPACE_URL, f"motif-forge:eval:{case['case_id']}")

    first = build_s1_composition(project_id, seed=seed)
    repeated = build_s1_composition(project_id, seed=seed)

    assert first.content_hash == repeated.content_hash
    assert first.arrangement == repeated.arrangement
    assert first.duration_seconds == pytest.approx(72.0)
    assert validate_s1_arrangement(first.arrangement) == ()
    assert compute_change_impact(first.commands) is ChangeImpact.L3
    assert len(first.arrangement.sections) == 4
    assert len(first.arrangement.tracks) == 4
    assert {track.role for track in first.arrangement.tracks} == {
        TrackRole.HARMONY,
        TrackRole.MELODY,
        TrackRole.BASS,
        TrackRole.RHYTHM,
    }
    assert all(
        isinstance(clip, NoteClip) and clip.notes
        for track in first.arrangement.tracks
        for clip in track.clips
    )


def test_s1_eval_set_has_twenty_unique_versioned_cases() -> None:
    cases = _cases()

    assert len(cases) >= 20
    assert len({str(case["case_id"]) for case in cases}) == len(cases)
    assert len({int(case["seed"]) for case in cases}) == len(cases)
