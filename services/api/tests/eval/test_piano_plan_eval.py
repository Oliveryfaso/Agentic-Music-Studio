"""P2.2 compiler Eval: musical intent dimensions, not model or listening scores."""

from pathlib import Path
from uuid import UUID

import pytest
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.ir import ArrangementIRV3, EnsemblePianoRenderProfile
from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan

DATA = Path(__file__).parents[2] / "src/motif_forge/resources/scores/ode-melody.musicxml"


def test_bounded_piano_plan_density_register_and_velocity_follow_semantic_parameters_eval():
    project = UUID(int=528)
    base = score_to_arrangement(
        parse_musicxml(DATA.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    tracks = []
    for request, grid, octave, velocity, gate in (
        (1, (0, 8), 2, 36, 3),
        (2, tuple(range(0, 16, 2)), 3, 72, 2),
    ):
        plan = AccompanimentPlan(
            summary="轻柔低音" if octave == 2 else "较高、更活跃",
            bars=tuple(
                BarPlan(
                    bar=bar, chord="G", grid=grid, octave=octave, velocity=velocity, gate_steps=gate
                )
                for bar in range(1, 17)
            ),
        )
        tracks.append(compile_piano_plan(base, plan, request_id=UUID(int=request)))
    quiet, active = (track.clips[0].notes for track in tracks)
    assert len(quiet) == 32 and len(active) == 128, "ACCOMPANIMENT_DENSITY_MISMATCH"
    assert max(note.pitch for note in quiet) < min(note.pitch for note in active), (
        "ACCOMPANIMENT_REGISTER_MISMATCH"
    )
    assert {note.velocity for note in quiet} == {36}
    assert {note.velocity for note in active} == {72}, "ACCOMPANIMENT_VELOCITY_MISMATCH"
    candidate = ArrangementIRV3.model_validate(
        {
            **base.model_dump(),
            "schema_version": "arrangement-ir.v3",
            "render_profile": EnsemblePianoRenderProfile(),
            "tracks": (*base.tracks, tracks[1]),
        }
    )
    assert candidate.tracks[0] == base.tracks[0], "CLASSICAL_SOURCE_PRESERVED"
    assert candidate.performance_plan == base.performance_plan


def test_original_track_rewrite_has_explicit_failure_label_eval():
    project = UUID(int=528)
    base = score_to_arrangement(
        parse_musicxml(DATA.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    plan = AccompanimentPlan(
        summary="有界伴奏",
        bars=tuple(
            BarPlan(bar=bar, chord="G", grid=(0,), octave=2, velocity=54) for bar in range(1, 17)
        ),
    )
    added = compile_piano_plan(base, plan, request_id=UUID(int=1))
    candidate = ArrangementIRV3.model_validate(
        {
            **base.model_dump(),
            "schema_version": "arrangement-ir.v3",
            "render_profile": EnsemblePianoRenderProfile(),
            "tracks": (*base.tracks, added),
        }
    )
    with pytest.raises(ValueError, match="ACCOMPANIMENT_TARGET_INVALID"):
        compile_piano_plan(
            candidate,
            plan,
            request_id=UUID(int=2),
            target_track_id=base.tracks[0].track_id,
            start_bar=9,
            end_bar=12,
        )
