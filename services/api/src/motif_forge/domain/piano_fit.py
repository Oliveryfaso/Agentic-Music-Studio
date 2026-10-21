"""Advisory musical facts for reviewed melodies; no edits or taste certification."""

from __future__ import annotations

from typing import Any

from motif_forge.domain.ir import ArrangementIR, NoteClip, NoteEvent
from motif_forge.domain.reviewed_scores import reviewed_source

FIT_POLICY_VERSION = "piano-musical-fit-context.v1"
_TRIADS = {
    "C": {0, 4, 7},
    "Dm": {2, 5, 9},
    "Em": {4, 7, 11},
    "F": {5, 9, 0},
    "G": {7, 11, 2},
    "Am": {9, 0, 4},
    "Bm": {11, 2, 6},
    "D": {2, 6, 9},
}
# Descriptive reductions checked against the pinned source-original voices.
# They are separate from historical manifest.default_chords (a rule baseline).
# c01 voicetwo mm6/7/8/14/16; c02 vThree mm2/4/5/6/8;
# j01 partOneLHvI first8 (=whole-score mm9..16), m4/m5/m6/m8.
# Sevenths/inversions/chromatic inner voices are explicitly NOT reconstructed.
_SOURCE_ANCHORS = {
    "c01-minuet-g-a16.v1": ((6, "G"), (7, "D"), (8, "D"), (14, "G"), (16, "G")),
    "c02-la-candeur-a8.v1": ((2, "F"), (4, "C"), (5, "G"), (6, "C"), (8, "G")),
    "j01-bethena-a-first8.v1": ((1, "G"), (3, "D"), (4, "Em"), (5, "C"), (6, "G"), (8, "D")),
}
_CADENCES = {
    "c01-minuet-g-a16.v1": ((8, "D"), (16, "G")),
    "c02-la-candeur-a8.v1": ((8, "G"),),
    "j01-bethena-a-first8.v1": ((8, "D"),),
}


def _resolved_short_tone(notes: list[NoteEvent], index: int, chord: set[int]) -> bool:
    """Only a local passing/neighbor heuristic, interpreted per candidate chord."""
    if not 0 < index < len(notes) - 1:
        return False
    before, note, after = notes[index - 1 : index + 2]
    if (
        note.duration_tick > 240
        or before.start_tick + before.duration_tick != note.start_tick
        or note.start_tick + note.duration_tick != after.start_tick
        or before.pitch % 12 not in chord
        or after.pitch % 12 not in chord
    ):
        return False
    left, right = note.pitch - before.pitch, after.pitch - note.pitch
    return 0 < abs(left) <= 2 and 0 < abs(right) <= 2


def piano_fit_context(
    base: ArrangementIR,
    *,
    start_bar: int,
    end_bar: int,
    include_harmony: bool = True,
) -> dict[str, Any]:
    source = reviewed_source(base)
    if not 1 <= start_bar <= end_bar <= source.measures:
        raise ValueError("ACCOMPANIMENT_SCOPE_INVALID")
    clip = base.tracks[0].clips[0]
    if not isinstance(clip, NoteClip):
        raise ValueError("CLASSICAL_SOURCE_REQUIRED")
    notes = sorted(clip.notes, key=lambda n: n.start_tick)
    allowed = (
        ("C", "Dm", "Em", "F", "G", "Am")
        if source.tonic == "C"
        else ("G", "Am", "Bm", "C", "D", "Em")
    )
    bt = source.bar_ticks
    candidates = []
    for bar in range(start_bar, end_bar + 1):
        first, last = (bar - 1) * bt, bar * bt
        scores = []
        for order, name in enumerate(allowed):
            score = 0.0
            for i, note in enumerate(notes):
                ticks = max(
                    0, min(last, note.start_tick + note.duration_tick) - max(first, note.start_tick)
                )
                if not ticks:
                    continue
                accent = 4 if note.start_tick % bt == 0 else 2 if note.start_tick % 480 == 0 else 1
                weight = ticks * accent
                if note.pitch % 12 in _TRIADS[name]:
                    score += weight
                else:
                    score -= weight * (0.25 if _resolved_short_tone(notes, i, _TRIADS[name]) else 1)
            scores.append((-score, order, name))
        candidates.append([bar, [row[2] for row in sorted(scores)[:2]]])
    # Exact repeated-bar identity helps avoid arbitrary changes to the same phrase.
    fingerprints: dict[tuple[tuple[int, int, int], ...], int] = {}
    pairs = []
    for bar in range(1, source.measures + 1):
        signature = tuple(
            (n.start_tick - (bar - 1) * bt, n.pitch, n.duration_tick)
            for n in notes
            if (bar - 1) * bt <= n.start_tick < bar * bt
        )
        if signature and signature in fingerprints and start_bar <= bar <= end_bar:
            pairs.append([fingerprints[signature], bar])
        else:
            fingerprints[signature] = bar
    ending = max(n.start_tick + n.duration_tick for n in notes)
    rest_step = (
        (ending - (source.measures - 1) * bt) // 120 if ending < source.measures * bt else None
    )
    return {
        "policy": FIT_POLICY_VERSION,
        "pulse_steps": list(range(0, source.beats * 4, 4)),
        "bar_candidates": candidates if include_harmony else [],
        "source_anchors": [
            [b, c] for b, c in _SOURCE_ANCHORS.get(source.score_id, ()) if start_bar <= b <= end_bar
        ]
        if include_harmony
        else [],
        "cadences": [
            [b, c] for b, c in _CADENCES.get(source.score_id, ()) if start_bar <= b <= end_bar
        ]
        if include_harmony
        else [],
        "repeated_bars": pairs,
        "terminal_rest_start_step": rest_step if end_bar == source.measures else None,
        "palette_limit": (
            "source sevenths/inversions/chromatic inner voices omitted; cues are reductions"
        ),
    }
