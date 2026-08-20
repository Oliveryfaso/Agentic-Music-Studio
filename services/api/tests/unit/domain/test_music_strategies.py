from itertools import pairwise
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
                    tuple(
                        (
                            note.start_tick,
                            note.duration_tick,
                            note.pitch,
                            note.articulation,
                        )
                        for clip in track.clips
                        for note in clip.notes[:8]
                    ),
                )
                for track in result.build.arrangement.tracks
            )
        )

    assert len(signatures) == 4


def test_minimal_strategy_locks_bass_attacks_to_the_drum_grid() -> None:
    request = brief("minimal_electronic")
    result = MusicStrategyRouter().compile(
        uuid4(), brief=request, plan=build_fallback_plan(request), seed=29
    )
    tracks = {track.role: track for track in result.build.arrangement.tracks}
    bass_onsets = {
        clip.start_tick + note.start_tick
        for clip in tracks[TrackRole.BASS].clips
        for note in clip.notes
    }
    drum_onsets = {
        clip.start_tick + note.start_tick
        for clip in tracks[TrackRole.RHYTHM].clips
        for note in clip.notes
    }

    assert bass_onsets <= drum_onsets
    issue = next(item for item in result.theory_report.issues if item.rule_id == "MIN-101")
    assert issue.evidence.measured_fact.startswith(f"{len(bass_onsets)}/{len(bass_onsets)}")


def test_classical_and_jazz_apply_style_specific_note_motion() -> None:
    router = MusicStrategyRouter()
    classical_request = brief("classical_chamber")
    jazz_request = brief("jazz_harmony_improvisation")
    classical = router.compile(
        uuid4(),
        brief=classical_request,
        plan=build_fallback_plan(classical_request),
        seed=31,
    )
    jazz = router.compile(
        uuid4(), brief=jazz_request, plan=build_fallback_plan(jazz_request), seed=31
    )

    classical_melody = next(
        track for track in classical.build.arrangement.tracks if track.role is TrackRole.MELODY
    )
    classical_pitches = [
        note.pitch for clip in classical_melody.clips for note in clip.notes[:16]
    ]
    assert (
        max(abs(right - left) for left, right in pairwise(classical_pitches)) <= 3
    )

    jazz_melody = next(
        track for track in jazz.build.arrangement.tracks if track.role is TrackRole.MELODY
    )
    jazz_starts = [note.start_tick for clip in jazz_melody.clips for note in clip.notes[:16]]
    assert any(start % 480 == 80 for start in jazz_starts)
    assert all(
        [note.start_tick for note in clip.notes]
        == sorted(note.start_tick for note in clip.notes)
        for track in jazz.build.arrangement.tracks
        for clip in track.clips
    )
    guide_issue = next(item for item in jazz.theory_report.issues if item.rule_id == "JAZ-101")
    assert "strong-beat guide tones" in guide_issue.evidence.measured_fact
