"""Explicit user-controlled accompaniment; no model, downloads or score mutation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field

from motif_forge.domain.commands import AppendPianoTrackCommand, AppendPianoTrackPayload
from motif_forge.domain.ir import (
    ArrangementIRV2,
    DomainModel,
    NoteClip,
    NoteEvent,
    Track,
    TrackRole,
    TrackType,
)
from motif_forge.domain.reviewed_scores import reviewed_source


class AccompanimentIntent(DomainModel):
    pattern: Literal["roots", "broken"]
    chords: tuple[Literal["G", "C", "D", "Em", "Am", "Bm", "F", "Dm"], ...] = Field(
        min_length=1, max_length=32
    )
    octave: Literal[2, 3] = 2
    velocity: int = Field(default=54, ge=32, le=80)


def accompaniment_command(
    base: ArrangementIRV2, intent: AccompanimentIntent, *, request_id: UUID
) -> AppendPianoTrackCommand:
    source = reviewed_source(base)
    bars = source.measures
    if len(intent.chords) != bars:
        raise ValueError("ACCOMPANIMENT_MEASURE_COUNT")
    roots = {
        "C": (0, 4, 7),
        "G": (7, 11, 14),
        "D": (2, 6, 9),
        "Em": (4, 7, 11),
        "Am": (9, 12, 16),
        "Bm": (11, 14, 18),
        "F": (5, 9, 12),
        "Dm": (2, 5, 9),
    }
    notes = []
    bar_ticks = base.time_signature_map[0].numerator * 480
    for bar, chord in enumerate(intent.chords):
        intervals = (
            (roots[chord][0],)
            if intent.pattern == "roots"
            else tuple(
                roots[chord][i] for i in (0, 1, 2, 1)[: base.time_signature_map[0].numerator]
            )
        )
        for beat, offset in enumerate(intervals):
            notes.append(
                NoteEvent(
                    note_id=uuid5(request_id, f"accompaniment:{bar}:{beat}"),
                    pitch=(intent.octave + 1) * 12 + offset,
                    start_tick=bar * bar_ticks + beat * 480,
                    duration_tick=480 if intent.pattern == "roots" else 360,
                    velocity=intent.velocity,
                )
            )
    track = Track(
        track_id=uuid5(request_id, "accompaniment-track"),
        track_type=TrackType.INSTRUMENT,
        name="低音点奏" if intent.pattern == "roots" else "分解伴奏",
        role=TrackRole.BASS,
        gain_db=-10.0,
        instrument_ref="builtin:jazz-piano",
        clips=(
            NoteClip(
                clip_id=uuid5(request_id, "accompaniment-clip"),
                start_tick=0,
                duration_tick=base.duration_tick,
                notes=tuple(notes),
            ),
        ),
    )
    return AppendPianoTrackCommand(
        command_id=uuid5(request_id, "append-piano"),
        client_sequence=0,
        payload=AppendPianoTrackPayload(track=track),
    )
