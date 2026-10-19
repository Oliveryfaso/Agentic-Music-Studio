from pathlib import Path
from uuid import UUID, uuid4

import pytest
from motif_forge.application.undo import build_inverse_commands
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import apply_commands
from motif_forge.domain.ir import read_arrangement_json

DATA = Path(__file__).parents[3] / "src/motif_forge/resources/scores/ode-melody.musicxml"
PROJECT = UUID("11111111-1111-4111-8111-111111111111")


def score():
    return parse_musicxml(DATA.read_bytes(), namespace=PROJECT)


def test_curated_melody_has_exact_measures_notes_pitch_time_and_stable_ids():
    parsed = score()
    assert parsed.measure_count == 16 and len(parsed.notes) == 62
    assert parsed.bpm == 100 and parsed.beats == 4 and parsed.tonic == "G"
    assert [n.pitch for n in parsed.notes[:8]] == [71, 71, 72, 74, 74, 72, 71, 69]
    assert max(n.start_tick + n.duration_tick for n in parsed.notes) == 30720
    assert parsed == score()
    assert len({n.note_id for n in parsed.notes}) == len(parsed.notes)
    assert parsed.notes[0].measure_id == "m01" and parsed.notes[-1].measure_id == "m16"


@pytest.mark.parametrize("feature", [b'<tie type="start"/>', b"<time-modification/>", b"<chord/>"])
def test_import_fails_closed_on_unsupported_musical_semantics(feature):
    data = DATA.read_bytes().replace(b"<pitch>", feature + b"<pitch>", 1)
    with pytest.raises(ValueError, match="SCORE_FEATURE_UNSUPPORTED"):
        parse_musicxml(data, namespace=PROJECT)


def test_import_rejects_unsafe_xml_and_inexact_measure_instead_of_silent_quantization():
    with pytest.raises(ValueError, match="SCORE_XML_UNSAFE"):
        parse_musicxml(b'<!DOCTYPE score [<!ENTITY x "x">]><score-partwise/>', namespace=PROJECT)
    with pytest.raises(ValueError, match="SCORE_MEASURE_DURATION"):
        parse_musicxml(
            DATA.read_bytes().replace(b"<duration>480</duration>", b"<duration>479</duration>", 1),
            namespace=PROJECT,
        )


def test_add_a_quiet_track_preserves_original_and_exact_parent_undo():
    base = score_to_arrangement(
        score(), project_id=PROJECT, source_ref="score:mutopia-528-melody.v1"
    )
    assert base.schema_version == "arrangement-ir.v2" and base.tracks[0].locked_ranges
    assert read_arrangement_json(base.model_dump_json()) == base
    intent = AccompanimentIntent(
        pattern="roots",
        chords=("G", "G", "D", "D", "G", "G", "D", "G", "D", "D", "D", "D", "G", "C", "D", "G"),
        octave=2,
        velocity=54,
    )
    command = accompaniment_command(base, intent, request_id=uuid4())
    candidate = apply_commands(base, (command,))
    assert candidate.schema_version == "arrangement-ir.v3" and len(candidate.tracks) == 2
    assert candidate.tracks[0] == base.tracks[0]
    assert candidate.performance_plan == base.performance_plan
    added = candidate.tracks[1]
    assert len(added.clips[0].notes) == 16 and added.gain_db < 0
    assert all(
        n.pitch < min(n.pitch for n in base.tracks[0].clips[0].notes) for n in added.clips[0].notes
    )
    inverse = build_inverse_commands(base, candidate, (command,), actor_id="human:local")
    assert apply_commands(candidate, inverse) == base
    assert arrangement_content_hash(
        read_arrangement_json(candidate.model_dump_json())
    ) == arrangement_content_hash(candidate)


def test_accompaniment_rejects_incomplete_harmony_or_unapproved_source():
    base = score_to_arrangement(
        score(), project_id=PROJECT, source_ref="score:mutopia-528-melody.v1"
    )
    with pytest.raises(ValueError, match="ACCOMPANIMENT_MEASURE_COUNT"):
        accompaniment_command(
            base,
            AccompanimentIntent(pattern="roots", chords=("G",), octave=2, velocity=54),
            request_id=uuid4(),
        )
    unknown = base.model_copy(update={"provenance": ()})
    with pytest.raises(ValueError, match="CLASSICAL_SOURCE_REQUIRED"):
        accompaniment_command(
            unknown,
            AccompanimentIntent(pattern="roots", chords=("G",) * 16, octave=2, velocity=54),
            request_id=uuid4(),
        )


def test_two_part_projection_is_versioned_and_old_single_track_contract_stays_strict():
    from motif_forge.application.rendering import compile_audio_graph
    from motif_forge.domain.ir import ArrangementIRV2
    from motif_forge.domain.revisions import versions_for_arrangement

    base = score_to_arrangement(
        score(), project_id=PROJECT, source_ref="score:mutopia-528-melody.v1"
    )
    command = accompaniment_command(
        base,
        AccompanimentIntent(pattern="broken", chords=("G",) * 16, octave=2, velocity=54),
        request_id=uuid4(),
    )
    candidate = apply_commands(base, (command,))
    projection = compile_audio_graph(candidate)
    assert projection.graph["schemaVersion"] == "audio-graph-spec.v3"
    assert projection.graph["engineVersion"] == "motif-forge-audio-engine.v3"
    assert len(projection.graph["tracks"]) == 2
    source_projection = compile_audio_graph(base).graph["tracks"][0]
    assert source_projection in projection.graph["tracks"]
    assert versions_for_arrangement(candidate).domain_schema == "arrangement-ir.v3"
    invalid = candidate.model_dump(mode="json")
    invalid["schema_version"] = "arrangement-ir.v2"
    invalid["render_profile"]["engine_version"] = "motif-forge-audio-engine.v2"
    import json

    with pytest.raises(ValueError, match="PIANO_SINGLE_TRACK_REQUIRED"):
        ArrangementIRV2.model_validate_json(json.dumps(invalid))
