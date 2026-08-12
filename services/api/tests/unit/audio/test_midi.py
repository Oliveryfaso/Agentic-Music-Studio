from __future__ import annotations

from uuid import UUID

from motif_forge.audio.midi import arrangement_to_midi
from motif_forge.domain.composition import build_s1_composition


def test_arrangement_to_midi_is_deterministic_and_contains_four_tracks() -> None:
    arrangement = build_s1_composition(
        UUID("10000000-0000-4000-8000-000000000066"), seed=66
    ).arrangement

    first = arrangement_to_midi(arrangement)
    repeated = arrangement_to_midi(arrangement)

    assert first == repeated
    assert first[0:4] == b"MThd"
    assert int.from_bytes(first[10:12], "big") == 5  # tempo/meta + four instrument tracks
    assert int.from_bytes(first[12:14], "big") == 480
    assert first.count(b"MTrk") == 5
