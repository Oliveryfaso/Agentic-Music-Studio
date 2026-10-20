"""Prove selected harmony from saved recipes; never infer an ambiguous chord."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.commands import AppendPianoTrackCommand
from motif_forge.domain.ir import ArrangementIR, NoteClip, NoteEvent, Track
from motif_forge.domain.piano_plan import PianoPlan, read_piano_plan
from motif_forge.domain.reviewed_scores import reviewed_source

_TRIADS = {
    "G": (7, 11, 14),
    "C": (0, 4, 7),
    "D": (2, 6, 9),
    "Em": (4, 7, 11),
    "Am": (9, 12, 16),
    "Bm": (11, 14, 18),
    "F": (5, 9, 12),
    "Dm": (2, 5, 9),
}


def _notes(arrangement: ArrangementIR, bar: int) -> tuple[NoteEvent, ...] | None:
    if len(arrangement.tracks) != 2 or len(arrangement.tracks[1].clips) != 1:
        return None
    clip = arrangement.tracks[1].clips[0]
    if not isinstance(clip, NoteClip) or clip.start_tick != 0:
        return None
    ticks = reviewed_source(arrangement).bar_ticks
    return tuple(n for n in clip.notes if (bar - 1) * ticks <= n.start_tick < bar * ticks)


def _explicit_rule_chord(track: Track, bar: int, *, bar_ticks: int, legacy: bool) -> str | None:
    """Recognize only the recorded P2.1 roots/broken recipe, not general harmony."""
    if len(track.clips) != 1 or not isinstance(track.clips[0], NoteClip):
        return None
    notes = tuple(
        n for n in track.clips[0].notes if (bar - 1) * bar_ticks <= n.start_tick < bar * bar_ticks
    )
    count = 1 if track.name == "低音点奏" else bar_ticks // 480 if track.name == "分解伴奏" else 0
    if not count or len(notes) != count:
        return None
    matches = []
    for chord, tones in _TRIADS.items():
        if legacy and chord in {"F", "Dm"}:
            continue
        for octave in (2, 3):
            if all(
                n.start_tick == (bar - 1) * bar_ticks + i * 480
                and n.duration_tick == (480 if count == 1 else 360)
                and n.pitch == (octave + 1) * 12 + tones[(0, 1, 2, 1)[i]]
                for i, n in enumerate(notes)
            ):
                matches.append(chord)
    return matches[0] if len(matches) == 1 else None


async def resolve_piano_harmony(
    projects: UnitOfWorkFactory,
    store: Any,
    *,
    revision_id: UUID,
    base: ArrangementIR,
    start_bar: int,
    end_bar: int,
) -> dict[int, str]:
    source = reviewed_source(base)
    if not 1 <= start_bar <= end_bar <= source.measures:
        raise ApplicationError("ACCOMPANIMENT_SCOPE_INVALID", "The source bar scope is invalid.")
    result: dict[int, str] = {}
    current_id: UUID | None = revision_id
    async with projects() as tx:
        for _ in range(64):
            if current_id is None:
                break
            revision = await tx.get_revision(current_id)
            if revision is None or revision.project_id != base.project_id:
                break
            matching = {
                bar
                for bar in range(start_bar, end_bar + 1)
                if bar not in result
                and _notes(base, bar) is not None
                and _notes(base, bar) == _notes(revision.arrangement_ir, bar)
                and revision.arrangement_ir.tracks[1].track_id == base.tracks[1].track_id
            }
            if matching and revision.source_run_id is not None:
                record = await store.read(revision.source_run_id)
                if record is not None:
                    plan = read_piano_plan(json.dumps(record["plan"]))
                    result.update({p.bar: p.chord for p in plan.bars if p.bar in matching})
            if matching.difference(result):
                for command in await tx.list_revision_commands(revision.revision_id):
                    if (
                        isinstance(command, AppendPianoTrackCommand)
                        and command.payload.track == revision.arrangement_ir.tracks[1]
                    ):
                        for bar in matching.difference(result):
                            chord = _explicit_rule_chord(
                                command.payload.track,
                                bar,
                                bar_ticks=source.bar_ticks,
                                legacy=source.score_id == "mutopia-528-melody.v1",
                            )
                            if chord is not None:
                                result[bar] = chord
            if len(result) == end_bar - start_bar + 1:
                return result
            current_id = revision.parent_revision_id
    raise ApplicationError(
        "PIANO_HARMONY_UNVERIFIED",
        "The selected harmony cannot be verified from a saved Flash or explicit rule recipe.",
    )


def require_preserved_harmony(plan: PianoPlan, harmony: dict[int, str]) -> None:
    if {p.bar: p.chord for p in plan.bars} != harmony:
        raise ApplicationError(
            "PIANO_HARMONY_CHANGED",
            "Local piano edits must preserve the verified harmony of every selected bar.",
        )
