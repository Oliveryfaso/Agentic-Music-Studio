from uuid import UUID, uuid4

import pytest
from motif_forge.application.classical_import import ClassicalScoreRequest, reviewed_score
from motif_forge.application.undo import build_inverse_commands
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import apply_commands
from motif_forge.domain.ir import ProvenanceRef

CASES = [
    ("c01-minuet-g-a16.v1", 16, 3, 64, 100, "G"),
    ("c02-la-candeur-a8.v1", 8, 4, 61, 112, "C"),
    ("j01-bethena-a-first8.v1", 8, 3, 26, 120, "G"),
]


@pytest.mark.parametrize("score_id,bars,beats,notes,bpm,tonic", CASES)
def test_reviewed_import_and_rule_preview_have_real_meter_locked_source_and_exact_undo(
    score_id, bars, beats, notes, bpm, tonic
):
    assert ClassicalScoreRequest(score_id=score_id).score_id == score_id
    manifest, xml = reviewed_score(score_id)
    project = UUID(int=20261020)
    parsed = parse_musicxml(xml, namespace=project)
    assert (parsed.measure_count, parsed.beats, len(parsed.notes), parsed.bpm, parsed.tonic) == (
        bars,
        beats,
        notes,
        bpm,
        tonic,
    )
    assert parsed == parse_musicxml(xml, namespace=project)
    assert manifest["license"] == "Public Domain" and manifest["conversion"]
    assert all(s["sha256"] and s["url"] for s in manifest["sources"])
    base = score_to_arrangement(parsed, project_id=project, source_ref="score:" + score_id)
    assert base.duration_tick == (bars + 1) * beats * 480
    from motif_forge.audio.midi import arrangement_to_midi

    midi = arrangement_to_midi(base)
    assert b"\xff\x58\x04" + bytes((beats, 2, 24, 8)) in midi
    chords = tuple(manifest["default_chords"])
    command = accompaniment_command(
        base, AccompanimentIntent(pattern="broken", chords=chords), request_id=uuid4()
    )
    candidate = apply_commands(base, (command,))
    assert candidate.tracks[0] == base.tracks[0]
    added = candidate.tracks[1].clips[0].notes
    assert len(added) == bars * beats
    assert [n.start_tick for n in added[: beats + 1]] == list(range(0, (beats + 1) * 480, 480))
    assert max(n.start_tick + n.duration_tick for n in added) <= bars * beats * 480
    inverse = build_inverse_commands(base, candidate, (command,), actor_id="human:local")
    assert apply_commands(candidate, inverse) == base
    if tonic == "C":
        assert max(n.start_tick + n.duration_tick for n in parsed.notes) == bars * beats * 480 - 480


def test_reviewed_rule_source_rejects_hash_or_meter_forgery_and_unknown_id():
    from motif_forge.application.errors import ApplicationError

    with pytest.raises(ApplicationError):
        reviewed_score("../../unreviewed")
    _, xml = reviewed_score("j01-bethena-a-first8.v1")
    project = uuid4()
    base = score_to_arrangement(
        parse_musicxml(xml, namespace=project),
        project_id=project,
        source_ref="score:j01-bethena-a-first8.v1",
    )
    intent = AccompanimentIntent(pattern="roots", chords=("G",) * 8)
    forged = base.model_copy(
        update={
            "provenance": (
                ProvenanceRef(kind="asset", ref="score:j01-bethena-a-first8.v1", version="0" * 64),
            )
        }
    )
    with pytest.raises(ValueError, match="CLASSICAL_SOURCE_REQUIRED"):
        accompaniment_command(forged, intent, request_id=uuid4())
    wrong_meter = base.model_copy(
        update={
            "time_signature_map": (base.time_signature_map[0].model_copy(update={"numerator": 4}),)
        }
    )
    with pytest.raises(ValueError, match="CLASSICAL_SOURCE_REQUIRED"):
        accompaniment_command(wrong_meter, intent, request_id=uuid4())


def test_c_major_user_triads_include_f_and_dm_but_never_invent_a_seventh_or_inversion():
    from pydantic import ValidationError

    assert AccompanimentIntent(pattern="roots", chords=("F", "Dm")).chords == ("F", "Dm")
    with pytest.raises(ValidationError):
        AccompanimentIntent(pattern="roots", chords=("G7/B",))
