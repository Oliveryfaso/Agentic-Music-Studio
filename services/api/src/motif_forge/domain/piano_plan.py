"""Bounded semantic piano plans; pure compilation never changes a Revision."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID, uuid5

from motif_forge.domain.ir import (
    ArrangementIR,
    ArrangementIRV2,
    DomainModel,
    EnsemblePianoRenderProfile,
    EqPianoRenderProfile,
    MixPianoRenderProfile,
    NoteClip,
    NoteEvent,
    PianoEqProfile,
    PianoRenderProfile,
    Track,
    TrackRole,
    TrackType,
)
from motif_forge.domain.reviewed_scores import reviewed_source
from pydantic import Field, TypeAdapter, model_validator

_STEP_TICKS = 120
_TRIADS = {
    "C": (0, 4, 7),
    "G": (7, 11, 14),
    "D": (2, 6, 9),
    "Em": (4, 7, 11),
    "Am": (9, 12, 16),
    "Bm": (11, 14, 18),
    "F": (5, 9, 12),
    "Dm": (2, 5, 9),
}


class BarPlan(DomainModel):
    """One bar of triad arpeggiation; every onset and gate is exact in ticks."""

    bar: int = Field(ge=1, le=16)
    chord: Literal["G", "C", "D", "Em", "Am", "Bm"]
    grid: tuple[Annotated[int, Field(ge=0, le=15)], ...] = Field(min_length=1, max_length=8)
    octave: Literal[2, 3]
    velocity: int = Field(ge=32, le=80)
    gate_steps: int = Field(default=3, ge=1, le=4)

    @model_validator(mode="after")
    def validate_grid(self) -> Self:
        if tuple(sorted(set(self.grid))) != self.grid:
            raise ValueError("ACCOMPANIMENT_GRID_INVALID")
        if any(step + self.gate_steps > 16 for step in self.grid):
            raise ValueError("ACCOMPANIMENT_NOTE_OUT_OF_BAR")
        return self


class AccompanimentPlan(DomainModel):
    schema_version: Literal["accompaniment-plan.v1"] = "accompaniment-plan.v1"
    summary: str = Field(min_length=1, max_length=300)
    bars: tuple[BarPlan, ...] = Field(min_length=1, max_length=16)


class BarPlanV2(DomainModel):
    bar: int = Field(ge=1, le=16)
    chord: Literal["G", "C", "D", "Em", "Am", "Bm", "F", "Dm"]
    grid: tuple[Annotated[int, Field(ge=0, le=15)], ...] = Field(min_length=1, max_length=8)
    octave: Literal[2, 3]
    velocity: int = Field(ge=32, le=80)
    gate_steps: int = Field(default=3, ge=1, le=4)

    @model_validator(mode="after")
    def validate_grid(self) -> Self:
        if tuple(sorted(set(self.grid))) != self.grid:
            raise ValueError("ACCOMPANIMENT_GRID_INVALID")
        return self


class AccompanimentPlanV2(DomainModel):
    schema_version: Literal["accompaniment-plan.v2"] = "accompaniment-plan.v2"
    summary: str = Field(min_length=1, max_length=300)
    beats_per_bar: Literal[3, 4]
    bars: tuple[BarPlanV2, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_meter(self) -> Self:
        if any(
            step + bar.gate_steps > self.beats_per_bar * 4 for bar in self.bars for step in bar.grid
        ):
            raise ValueError("ACCOMPANIMENT_NOTE_OUT_OF_BAR")
        return self


PianoPlan = AccompanimentPlan | AccompanimentPlanV2


def read_piano_plan(value: str) -> PianoPlan:
    return TypeAdapter(PianoPlan).validate_json(value, strict=True)


def compile_piano_plan(
    base: ArrangementIR,
    plan: PianoPlan,
    *,
    request_id: UUID,
    target_track_id: UUID | None = None,
    start_bar: int = 1,
    end_bar: int = 16,
) -> Track:
    """Return an added/replacement Track for application-owned preview and HITL.

    Only a version-pinned reviewed melody plus its release rest is accepted.
    Editing removes only notes wholly inside the selected bars. A boundary-spanning
    note or a removed note's performance override fails closed; nothing is clipped,
    discarded, or reset implicitly. The caller still owns non-target comparison,
    ArrangementIR validation, ChangeImpact, budget, and candidate persistence.
    """
    piano = _require_source(base)
    source = reviewed_source(base)
    legacy = source.score_id == "mutopia-528-melody.v1"
    if legacy != isinstance(plan, AccompanimentPlan):
        raise ValueError("ACCOMPANIMENT_PLAN_VERSION_MISMATCH")
    if isinstance(plan, AccompanimentPlanV2):
        if plan.beats_per_bar != source.beats:
            raise ValueError("ACCOMPANIMENT_METER_MISMATCH")
        allowed = (
            {"C", "Dm", "Em", "F", "G", "Am"}
            if source.tonic == "C"
            else {"G", "Am", "Bm", "C", "D", "Em"}
        )
        if any(bar.chord not in allowed for bar in plan.bars):
            raise ValueError("ACCOMPANIMENT_CHORD_UNSUPPORTED")
    bar_ticks = source.bar_ticks
    version = str(base.schema_version)
    if target_track_id is None:
        if (
            version != "arrangement-ir.v2"
            or len(base.tracks) != 1
            or start_bar != 1
            or end_bar != source.measures
        ):
            raise ValueError("ACCOMPANIMENT_SCOPE_INVALID")
        _require_bar_coverage(plan, start_bar, end_bar)
        return Track(
            track_id=uuid5(request_id, "piano-plan:track"),
            track_type=TrackType.INSTRUMENT,
            name="AI 钢琴伴奏",
            role=TrackRole.BASS,
            gain_db=-10.0,
            instrument_ref="builtin:jazz-piano",
            clips=(
                NoteClip(
                    clip_id=uuid5(request_id, "piano-plan:clip"),
                    start_tick=0,
                    duration_tick=base.duration_tick,
                    notes=_compile_notes(plan, request_id, bar_ticks),
                ),
            ),
        )
    if (
        version not in ("arrangement-ir.v3", "arrangement-ir.v4", "arrangement-ir.v5")
        or len(base.tracks) != 2
        or not 1 <= start_bar <= end_bar <= source.measures
        or end_bar - start_bar >= 4
    ):
        raise ValueError("ACCOMPANIMENT_SCOPE_INVALID")
    target = base.tracks[1]
    if (
        target.track_id != target_track_id
        or target.track_id == base.tracks[0].track_id
        or target.locked_ranges
        or target.track_type is not TrackType.INSTRUMENT
        or target.instrument_ref != "builtin:jazz-piano"
        or len(target.clips) != 1
        or not isinstance(target.clips[0], NoteClip)
        or target.clips[0].start_tick != 0
        or target.clips[0].duration_tick != base.duration_tick
    ):
        raise ValueError("ACCOMPANIMENT_TARGET_INVALID")
    _require_bar_coverage(plan, start_bar, end_bar)
    clip = target.clips[0]
    first, last = (start_bar - 1) * bar_ticks, end_bar * bar_ticks
    removed_ids = set()
    retained = []
    for note in clip.notes:
        end = note.start_tick + note.duration_tick
        overlaps = note.start_tick < last and end > first
        if overlaps:
            if note.start_tick < first or end > last:
                raise ValueError("ACCOMPANIMENT_SCOPE_INVALID")
            removed_ids.add(note.note_id)
        else:
            retained.append(note)
    if any(
        item.track_id == target_track_id
        and item.clip_id == clip.clip_id
        and item.note_id in removed_ids
        for item in piano.performance_plan.notes
    ):
        raise ValueError("ACCOMPANIMENT_PERFORMANCE_CONFLICT")
    # Preserve the retained subsequence even when the input notes are not time-sorted.
    insert_at = next(
        (index for index, note in enumerate(retained) if note.start_tick >= last), len(retained)
    )
    notes = (
        *retained[:insert_at],
        *_compile_notes(plan, request_id, bar_ticks),
        *retained[insert_at:],
    )
    updated_clip = NoteClip.model_validate({**clip.model_dump(), "notes": notes})
    return Track.model_validate({**target.model_dump(), "clips": (updated_clip,)})


def _require_source(base: ArrangementIR) -> ArrangementIRV2:
    version = str(base.schema_version)
    reviewed_source(base)
    if (
        not isinstance(base, ArrangementIRV2)
        or version
        not in ("arrangement-ir.v2", "arrangement-ir.v3", "arrangement-ir.v4", "arrangement-ir.v5")
        or not base.tracks
    ):
        raise ValueError("CLASSICAL_SOURCE_REQUIRED")
    expected_profile = (
        EqPianoRenderProfile(eq_profile=PianoEqProfile())
        if version == "arrangement-ir.v5"
        else MixPianoRenderProfile()
        if version == "arrangement-ir.v4"
        else EnsemblePianoRenderProfile()
        if version == "arrangement-ir.v3"
        else PianoRenderProfile()
    )
    source = base.tracks[0]
    if (
        base.render_profile != expected_profile
        or source.track_type is not TrackType.INSTRUMENT
        or source.role is not TrackRole.MELODY
        or source.instrument_ref != "builtin:jazz-piano"
        or len(source.locked_ranges) != 1
        or source.locked_ranges[0].start_tick != 0
        or source.locked_ranges[0].end_tick != base.duration_tick
        or len(source.clips) != 1
        or not isinstance(source.clips[0], NoteClip)
        or source.clips[0].start_tick != 0
        or source.clips[0].duration_tick != base.duration_tick
    ):
        raise ValueError("CLASSICAL_SOURCE_REQUIRED")
    return base


def _require_bar_coverage(plan: PianoPlan, start_bar: int, end_bar: int) -> None:
    expected = tuple(range(start_bar, end_bar + 1))
    if tuple(sorted(item.bar for item in plan.bars)) != expected:
        raise ValueError("ACCOMPANIMENT_BAR_COVERAGE")


def _compile_notes(plan: PianoPlan, request_id: UUID, bar_ticks: int) -> tuple[NoteEvent, ...]:
    notes = []
    bars: tuple[BarPlan | BarPlanV2, ...] = plan.bars
    for bar in sorted(bars, key=lambda item: item.bar):
        for index, step in enumerate(bar.grid):
            offset = _TRIADS[bar.chord][(0, 1, 2, 1)[index % 4]]
            notes.append(
                NoteEvent(
                    note_id=uuid5(request_id, f"piano-plan:bar:{bar.bar}:step:{step}"),
                    pitch=(bar.octave + 1) * 12 + offset,
                    start_tick=(bar.bar - 1) * bar_ticks + step * _STEP_TICKS,
                    duration_tick=bar.gate_steps * _STEP_TICKS,
                    velocity=bar.velocity,
                )
            )
    return tuple(notes)
