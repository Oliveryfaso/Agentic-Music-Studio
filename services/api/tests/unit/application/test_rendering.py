from __future__ import annotations

from uuid import UUID

import pytest
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.music_strategies import MusicStrategyRouter

PROJECT_ID = UUID("10000000-0000-4000-8000-000000000022")


def test_ir_projection_preserves_tick_truth_and_produces_stable_audio_graph() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=22).arrangement

    first = compile_audio_graph(arrangement)
    repeated = compile_audio_graph(arrangement)

    assert first.schema_version == "audio-graph-projection.v1"
    assert first.graph_hash == repeated.graph_hash
    assert first.graph == repeated.graph
    assert first.graph["schemaVersion"] == "audio-graph-spec.v1"
    assert first.graph["engineVersion"] == "motif-forge-audio-engine.v1"
    assert first.graph["durationSeconds"] == pytest.approx(72.0)
    assert first.graph["sampleRate"] == 48_000
    assert first.graph["channels"] == 2
    assert len(first.graph["tracks"]) == 4
    assert arrangement.duration_tick == 46_080


def test_ir_projection_maps_absolute_clip_and_note_ticks_to_seconds() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=23).arrangement

    projection = compile_audio_graph(arrangement)

    melody_track = next(
        track for track in projection.graph["tracks"] if track["name"] == "Glass Motif"
    )
    section_two_note = next(note for note in melody_track["notes"] if note["startSeconds"] >= 12.0)
    assert section_two_note["startSeconds"] == pytest.approx(12.0)
    assert section_two_note["durationSeconds"] == pytest.approx(0.5625)


def test_ir_projection_can_select_one_stem_but_rejects_unknown_or_duplicate_tracks() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=24).arrangement
    bass = next(track for track in arrangement.tracks if track.name == "Sub Foundation")

    stem = compile_audio_graph(arrangement, render_track_ids=(bass.track_id,))

    assert len(stem.graph["tracks"]) == 1
    assert stem.render_track_ids == (bass.track_id,)
    with pytest.raises(ValueError, match="RENDER_SCOPE_INVALID"):
        compile_audio_graph(arrangement, render_track_ids=(UUID(int=999),))
    with pytest.raises(ValueError, match="RENDER_SCOPE_INVALID"):
        compile_audio_graph(arrangement, render_track_ids=(bass.track_id, bass.track_id))


def test_ir_projection_rejects_unreviewed_instrument_reference() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=25).arrangement
    changed = arrangement.model_copy(
        update={
            "tracks": (
                arrangement.tracks[0].model_copy(update={"instrument_ref": "external:unknown"}),
                *arrangement.tracks[1:],
            )
        }
    )

    with pytest.raises(ValueError, match="INSTRUMENT_REF_UNSUPPORTED"):
        compile_audio_graph(changed)


@pytest.mark.parametrize(
    "style",
    [
        "minimal_electronic",
        "classical_chamber",
        "jazz_harmony_improvisation",
    ],
)
def test_reviewed_s4_palette_projects_to_the_lite_audio_engine(style: str) -> None:
    brief = CompositionBrief.model_validate(
        {
            "title": "S4 render boundary",
            "purpose": "Render a complete deterministic instrumental cue",
            "style": style,
            "duration_seconds": 60,
            "meter": "4/4",
            "target_key": "C major",
            "moods": ("focused",),
        },
        strict=True,
    )
    arrangement = (
        MusicStrategyRouter()
        .compile(PROJECT_ID, brief=brief, plan=build_fallback_plan(brief), seed=26)
        .build.arrangement
    )

    projection = compile_audio_graph(arrangement)

    assert len(projection.graph["tracks"]) == 4
    assert {track["kind"] for track in projection.graph["tracks"]} == {
        "synth",
        "sampler",
    }
