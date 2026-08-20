from uuid import uuid4

import pytest
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.domain.ir import TrackRole
from motif_forge.domain.music_strategies import MusicStrategyRouter

STYLES = (
    "synth_ambient",
    "minimal_electronic",
    "classical_chamber",
    "jazz_harmony_improvisation",
)


def brief(style: str) -> CompositionBrief:
    return CompositionBrief.model_validate(
        {
            "title": "Four strategy proof",
            "purpose": "Create a complete instrumental portfolio cue",
            "style": style,
            "duration_seconds": 60,
            "meter": "4/4",
            "target_bpm": None,
            "target_key": "C major",
            "moods": ("focused",),
        },
        strict=True,
    )


@pytest.mark.parametrize("style", STYLES)
def test_router_compiles_each_style_deterministically(style: str) -> None:
    request = brief(style)
    plan = build_fallback_plan(request)
    project_id = uuid4()
    router = MusicStrategyRouter()

    first = router.compile(project_id, brief=request, plan=plan, seed=17)
    replay = router.compile(project_id, brief=request, plan=plan, seed=17)

    assert first == replay
    assert first.pack.style == style
    assert not first.theory_report.blocking
    assert {track.role for track in first.build.arrangement.tracks} == {
        TrackRole.HARMONY,
        TrackRole.MELODY,
        TrackRole.BASS,
        TrackRole.RHYTHM,
    }
    assert first.build.duration_seconds <= 300


def test_four_strategies_produce_structurally_distinct_arrangements() -> None:
    router = MusicStrategyRouter()
    project_id = uuid4()
    signatures = set()

    for style in STYLES:
        request = brief(style)
        result = router.compile(
            project_id, brief=request, plan=build_fallback_plan(request), seed=23
        )
        signatures.add(
            tuple(
                (
                    track.name,
                    track.instrument_ref,
                    tuple(note.articulation for clip in track.clips for note in clip.notes[:4]),
                )
                for track in result.build.arrangement.tracks
            )
        )

    assert len(signatures) == 4
