from uuid import uuid4

import pytest
from motif_forge.application.classical_import import reviewed_score
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.ir import NoteEvent
from motif_forge.domain.piano_fit import _resolved_short_tone, piano_fit_context


def base(score="c02-la-candeur-a8.v1"):
    project = uuid4()
    _, xml = reviewed_score(score)
    return score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref="score:" + score
    )


def test_source_harmony_and_half_cadence_are_not_naive_pitch_histogram_or_final_tonic():
    result = piano_fit_context(base(), start_bar=1, end_bar=8)
    # F5 on the first eighth of m6 does not make the original C harmony "wrong".
    assert [6, "C"] in result["source_anchors"]
    assert [8, "G"] in result["cadences"] and [8, "C"] not in result["cadences"]
    assert result["terminal_rest_start_step"] == 12
    assert [2, ["F", "C"]] in result["bar_candidates"]


def test_locked_modify_receives_rhythm_facts_without_competing_reharmonization():
    result = piano_fit_context(base(), start_bar=5, end_bar=8, include_harmony=False)
    assert result["source_anchors"] == result["cadences"] == result["bar_candidates"] == []
    assert result["pulse_steps"] == [0, 4, 8, 12] and result["terminal_rest_start_step"] == 12


@pytest.mark.parametrize("pitches", [(60, 62, 64), (60, 62, 60)])
def test_short_resolved_passing_or_neighbor_is_not_treated_as_unresolved_clash(pitches):
    notes = [
        NoteEvent(note_id=uuid4(), pitch=p, start_tick=s, duration_tick=d, velocity=50)
        for p, s, d in zip(pitches, (0, 480, 720), (480, 240, 480), strict=True)
    ]
    assert _resolved_short_tone(notes, 1, {0, 4, 7})
    # Resolution over a rest cannot be assumed from pitch direction alone.
    notes[2] = notes[2].model_copy(update={"start_tick": 960})
    assert not _resolved_short_tone(notes, 1, {0, 4, 7})


def test_short_tone_with_no_chord_resolution_is_not_excused():
    notes = [
        NoteEvent(note_id=uuid4(), pitch=p, start_tick=i * 240, duration_tick=240, velocity=50)
        for i, p in enumerate((60, 62, 63))
    ]
    assert not _resolved_short_tone(notes, 1, {0, 4, 7})


def test_exact_repeated_minuet_bars_remain_visible_and_scope_is_bounded():
    b = base("c01-minuet-g-a16.v1")
    before = b.model_dump_json()
    c = piano_fit_context(b, start_bar=9, end_bar=12)
    assert c["repeated_bars"] == [[1, 9], [2, 10], [3, 11], [4, 12]]
    assert b.model_dump_json() == before and c["terminal_rest_start_step"] is None
    with pytest.raises(ValueError, match="SCOPE"):
        piano_fit_context(b, start_bar=1, end_bar=17)
