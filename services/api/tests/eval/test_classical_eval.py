"""P2 deterministic baseline: preservation and fail-closed notation, no model judgment."""

from uuid import UUID

import pytest
from motif_forge.application.classical_import import SOURCE_REF, reviewed_score
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import apply_commands


def test_classical_source_preserved_eval():
    project = UUID(int=528)
    source, xml = reviewed_score()
    original = score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref=SOURCE_REF
    )
    baseline = compile_audio_graph(original).graph
    for pattern, count in (("roots", 16), ("broken", 64)):
        intent = AccompanimentIntent(
            pattern=pattern, chords=tuple(source["default_chords"]), octave=2, velocity=54
        )
        command = accompaniment_command(original, intent, request_id=UUID(int=1))
        candidate = apply_commands(original, (command,))
        graph = compile_audio_graph(candidate).graph
        assert original.tracks[0] in candidate.tracks, "CLASSICAL_SOURCE_PRESERVED"
        assert baseline["tracks"][0] in graph["tracks"], "CLASSICAL_SOURCE_PRESERVED"
        assert (
            len(
                next(t for t in candidate.tracks if t.track_id != original.tracks[0].track_id)
                .clips[0]
                .notes
            )
            == count
        )
        assert graph["durationSeconds"] == baseline["durationSeconds"]


@pytest.mark.parametrize("notation", [b'<tie type="start"/>', b"<time-modification/>", b"<chord/>"])
def test_score_feature_unsupported_eval(notation):
    _, xml = reviewed_score()
    with pytest.raises(ValueError, match="SCORE_FEATURE_UNSUPPORTED"):
        parse_musicxml(xml.replace(b"<pitch>", notation + b"<pitch>", 1), namespace=UUID(int=528))


@pytest.mark.parametrize(
    "score_id", ["c01-minuet-g-a16.v1", "c02-la-candeur-a8.v1", "j01-bethena-a-first8.v1"]
)
def test_three_score_rule_preservation_and_unknown_semantic_contract_eval(score_id):
    from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan

    manifest, xml = reviewed_score(score_id)
    project = UUID(int=20261021)
    original = score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref="score:" + score_id
    )
    command = accompaniment_command(
        original,
        AccompanimentIntent(pattern="broken", chords=tuple(manifest["default_chords"])),
        request_id=UUID(int=2),
    )
    added = apply_commands(original, (command,))
    assert added.tracks[0] == original.tracks[0], "REVIEWED_SOURCE_PRESERVED"
    assert added.duration_tick == original.duration_tick, "ACTUAL_METER_PRESERVED"
    plan = AccompanimentPlan(
        summary="must not use the old semantic contract",
        bars=(BarPlan(bar=1, chord="G", grid=(0,), octave=2, velocity=54),),
    )
    with pytest.raises(ValueError, match="CLASSICAL_SOURCE_REQUIRED"):
        compile_piano_plan(original, plan, request_id=UUID(int=3))
