"""Deterministic high-level patterns and the S1 complete-song composer."""

from __future__ import annotations

from enum import StrEnum
from itertools import chain
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ConfigDict, Field, model_validator

from motif_forge.agent.schemas import CompositionPlan
from motif_forge.domain.ai_runs import composition_plan_content_hash
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import (
    AddTrackCommand,
    AddTrackPayload,
    EditorCommand,
    InitializeCompositionCommand,
    InitializeCompositionPayload,
    Selection,
    apply_commands,
)
from motif_forge.domain.errors import DomainIssue
from motif_forge.domain.ir import (
    PPQ,
    ArrangementIR,
    Articulation,
    DomainModel,
    KeyPoint,
    MeterPoint,
    MusicalMode,
    NoteClip,
    NoteEvent,
    ProvenanceRef,
    Section,
    TempoPoint,
    Track,
    TrackRole,
    TrackType,
    create_empty_arrangement,
)
from motif_forge.domain.timebase import ticks_to_seconds

COMPOSER_VERSION = "s1-deterministic-composer.v1"
SYNTH_AMBIENT_COMPILER_VERSION = "synth-ambient-compiler.v1"
S1_BPM = 80.0
S1_BARS = 24
S1_BAR_TICKS = PPQ * 4
S1_DURATION_TICKS = S1_BARS * S1_BAR_TICKS


class PatternRole(StrEnum):
    PAD = "pad"
    MELODY = "melody"
    BASS = "bass"
    RHYTHM = "rhythm"


class BarRange(DomainModel):
    start_bar: int = Field(ge=0, le=127)
    end_bar: int = Field(gt=0, le=128)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_bar <= self.start_bar:
            raise ValueError("end_bar must be greater than start_bar")
        return self


class MidiRegister(DomainModel):
    low_midi: int = Field(ge=0, le=127)
    high_midi: int = Field(ge=0, le=127)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.high_midi < self.low_midi:
            raise ValueError("high_midi must be greater than or equal to low_midi")
        return self


class PatternSpec(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        serialize_by_alias=True,
        validate_by_alias=True,
        validate_by_name=False,
    )

    schema_version: Literal["pattern-spec.v1"] = "pattern-spec.v1"
    pattern_id: UUID
    section_id: UUID
    track_role: PatternRole
    bar_range: BarRange
    chord_degrees: tuple[int, ...] = Field(min_length=1, max_length=32)
    rhythm_grid: tuple[int, ...] = Field(min_length=1, max_length=16)
    midi_register: MidiRegister = Field(alias="register", serialization_alias="register")
    density: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    syncopation: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    variation_seed: int = Field(ge=0, le=2**31 - 1)
    locked_constraints: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_pattern(self) -> Self:
        if any(degree < 1 or degree > 7 for degree in self.chord_degrees):
            raise ValueError("chord_degrees must use scale degrees 1 through 7")
        if len(self.chord_degrees) != self.bar_range.end_bar - self.bar_range.start_bar:
            raise ValueError("chord_degrees must contain one degree per bar")
        if tuple(sorted(set(self.rhythm_grid))) != self.rhythm_grid:
            raise ValueError("rhythm_grid must be sorted and unique")
        if any(step < 0 or step > 15 for step in self.rhythm_grid):
            raise ValueError("rhythm_grid steps must be within one 16-step bar")
        if any(not item.strip() for item in self.locked_constraints):
            raise ValueError("locked_constraints cannot contain blank values")
        return self


class CompositionBuild(DomainModel):
    schema_version: Literal["composition-build.v1"] = "composition-build.v1"
    seed: int = Field(ge=0, le=2**31 - 1)
    patterns: tuple[PatternSpec, ...] = Field(min_length=1)
    commands: tuple[EditorCommand, ...] = Field(min_length=1)
    arrangement: ArrangementIR
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_seconds: float = Field(gt=0.0, le=300.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_build(self) -> Self:
        if arrangement_content_hash(self.arrangement) != self.content_hash:
            raise ValueError("content_hash must match the built ArrangementIR")
        return self


_SCALE = (0, 2, 4, 5, 7, 9, 11)
_ROLE_REGISTER = {
    PatternRole.PAD: MidiRegister(low_midi=48, high_midi=72),
    PatternRole.MELODY: MidiRegister(low_midi=60, high_midi=84),
    PatternRole.BASS: MidiRegister(low_midi=36, high_midi=52),
    PatternRole.RHYTHM: MidiRegister(low_midi=36, high_midi=36),
}
_ROLE_TO_TRACK_ROLE = {
    PatternRole.PAD: TrackRole.HARMONY,
    PatternRole.MELODY: TrackRole.MELODY,
    PatternRole.BASS: TrackRole.BASS,
    PatternRole.RHYTHM: TrackRole.RHYTHM,
}
_INSTRUMENTS = {
    PatternRole.PAD: "builtin:warm_pad",
    PatternRole.MELODY: "builtin:glass_pluck",
    PatternRole.BASS: "builtin:sub_bass",
    PatternRole.RHYTHM: "builtin:click",
}
_TRACK_NAMES = {
    PatternRole.PAD: "Atmosphere Pad",
    PatternRole.MELODY: "Glass Motif",
    PatternRole.BASS: "Sub Foundation",
    PatternRole.RHYTHM: "Pulse",
}


def _stable_id(project_id: UUID, *parts: object) -> UUID:
    suffix = ":".join(str(part) for part in parts)
    return uuid5(NAMESPACE_URL, f"motif-forge:{project_id}:{suffix}")


def _sections(project_id: UUID) -> tuple[Section, ...]:
    definitions = (
        ("intro", 0, 4, "opening", 0.25),
        ("drift", 4, 12, "development", 0.48),
        ("bloom", 12, 20, "climax", 0.72),
        ("resolve", 20, 24, "resolution", 0.3),
    )
    return tuple(
        Section(
            section_id=_stable_id(project_id, "section", label),
            start_tick=start_bar * S1_BAR_TICKS,
            end_tick=end_bar * S1_BAR_TICKS,
            label=label.title(),
            function=function,
            energy=energy,
        )
        for label, start_bar, end_bar, function, energy in definitions
    )


def _progression(start_bar: int, end_bar: int) -> tuple[int, ...]:
    return {
        (0, 4): (1, 6, 4, 5),
        (4, 12): (1, 5, 6, 4, 1, 5, 4, 4),
        (12, 20): (6, 4, 1, 5, 6, 4, 5, 5),
        (20, 24): (1, 4, 1, 1),
    }[(start_bar, end_bar)]


def _patterns(
    project_id: UUID, seed: int, sections: tuple[Section, ...]
) -> tuple[PatternSpec, ...]:
    patterns: list[PatternSpec] = []
    grids = {
        PatternRole.PAD: (0,),
        PatternRole.MELODY: (0, 4, 8, 12),
        PatternRole.BASS: (0, 8),
        PatternRole.RHYTHM: (0, 4, 8, 12),
    }
    densities = {
        PatternRole.PAD: 0.35,
        PatternRole.MELODY: 0.55,
        PatternRole.BASS: 0.4,
        PatternRole.RHYTHM: 0.5,
    }
    for section_index, section in enumerate(sections):
        start_bar = section.start_tick // S1_BAR_TICKS
        end_bar = section.end_tick // S1_BAR_TICKS
        for role_index, role in enumerate(PatternRole):
            variation_seed = (seed * 1_103 + section_index * 97 + role_index * 31) % (2**31)
            patterns.append(
                PatternSpec(
                    pattern_id=_stable_id(project_id, "pattern", seed, section.section_id, role),
                    section_id=section.section_id,
                    track_role=role,
                    bar_range=BarRange(start_bar=start_bar, end_bar=end_bar),
                    chord_degrees=_progression(start_bar, end_bar),
                    rhythm_grid=grids[role],
                    register=_ROLE_REGISTER[role],
                    density=densities[role],
                    syncopation=0.15 if role is PatternRole.MELODY else 0.0,
                    variation_seed=variation_seed,
                    locked_constraints=("key:c-major", "meter:4/4", "tempo:80"),
                )
            )
    return tuple(patterns)


def _scale_pitch(degree: int, octave_base: int) -> int:
    return octave_base + _SCALE[(degree - 1) % 7]


def _compile_pad(project_id: UUID, pattern: PatternSpec) -> tuple[NoteEvent, ...]:
    notes: list[NoteEvent] = []
    for bar_offset, degree in enumerate(pattern.chord_degrees):
        root_index = degree - 1
        chord = tuple(
            48 + _SCALE[(root_index + step) % 7] + (12 if root_index + step >= 7 else 0)
            for step in (0, 2, 4)
        )
        local_start = bar_offset * S1_BAR_TICKS
        for voice, pitch in enumerate(chord):
            notes.append(
                NoteEvent(
                    note_id=_stable_id(project_id, pattern.pattern_id, "pad", bar_offset, voice),
                    pitch=pitch,
                    start_tick=local_start,
                    duration_tick=S1_BAR_TICKS - 60,
                    velocity=58 + voice * 4,
                    articulation=Articulation.LEGATO,
                )
            )
    return tuple(notes)


def _compile_melody(project_id: UUID, pattern: PatternSpec) -> tuple[NoteEvent, ...]:
    notes: list[NoteEvent] = []
    for bar_offset, degree in enumerate(pattern.chord_degrees):
        for step_index, grid_step in enumerate(pattern.rhythm_grid):
            selector = (pattern.variation_seed + bar_offset * 5 + step_index * 3) % 7
            scale_degree = ((degree - 1 + selector) % 7) + 1
            pitch = _scale_pitch(scale_degree, 60) + (12 if selector >= 5 else 0)
            notes.append(
                NoteEvent(
                    note_id=_stable_id(
                        project_id, pattern.pattern_id, "melody", bar_offset, step_index
                    ),
                    pitch=min(pitch, pattern.midi_register.high_midi),
                    start_tick=bar_offset * S1_BAR_TICKS + grid_step * (PPQ // 4),
                    duration_tick=PPQ * 3 // 4,
                    velocity=66 + (selector % 4) * 5,
                )
            )
    return tuple(notes)


def _compile_bass(project_id: UUID, pattern: PatternSpec) -> tuple[NoteEvent, ...]:
    notes: list[NoteEvent] = []
    for bar_offset, degree in enumerate(pattern.chord_degrees):
        root = _scale_pitch(degree, 36)
        for step_index, grid_step in enumerate(pattern.rhythm_grid):
            notes.append(
                NoteEvent(
                    note_id=_stable_id(
                        project_id, pattern.pattern_id, "bass", bar_offset, step_index
                    ),
                    pitch=(
                        root if step_index == 0 else min(root + 7, pattern.midi_register.high_midi)
                    ),
                    start_tick=bar_offset * S1_BAR_TICKS + grid_step * (PPQ // 4),
                    duration_tick=PPQ * 3 // 2,
                    velocity=72 if step_index == 0 else 60,
                )
            )
    return tuple(notes)


def _compile_rhythm(project_id: UUID, pattern: PatternSpec) -> tuple[NoteEvent, ...]:
    return tuple(
        NoteEvent(
            note_id=_stable_id(project_id, pattern.pattern_id, "pulse", bar, step_index),
            pitch=36,
            start_tick=bar * S1_BAR_TICKS + grid_step * (PPQ // 4),
            duration_tick=PPQ // 8,
            velocity=88 if grid_step == 0 else 60,
            articulation=Articulation.STACCATO,
        )
        for bar in range(pattern.bar_range.end_bar - pattern.bar_range.start_bar)
        for step_index, grid_step in enumerate(pattern.rhythm_grid)
    )


def _compile_pattern(project_id: UUID, pattern: PatternSpec) -> tuple[NoteEvent, ...]:
    if pattern.track_role is PatternRole.PAD:
        return _compile_pad(project_id, pattern)
    if pattern.track_role is PatternRole.MELODY:
        return _compile_melody(project_id, pattern)
    if pattern.track_role is PatternRole.BASS:
        return _compile_bass(project_id, pattern)
    return _compile_rhythm(project_id, pattern)


def _track(
    project_id: UUID, seed: int, role: PatternRole, patterns: tuple[PatternSpec, ...]
) -> Track:
    role_patterns = tuple(pattern for pattern in patterns if pattern.track_role is role)
    return Track(
        track_id=_stable_id(project_id, "track", role),
        track_type=TrackType.INSTRUMENT,
        name=_TRACK_NAMES[role],
        role=_ROLE_TO_TRACK_ROLE[role],
        gain_db=-6.0 if role is PatternRole.PAD else -4.0,
        pan=-0.12 if role is PatternRole.PAD else (0.12 if role is PatternRole.MELODY else 0.0),
        instrument_ref=_INSTRUMENTS[role],
        clips=tuple(
            NoteClip(
                clip_id=_stable_id(project_id, "clip", seed, pattern.section_id, role),
                start_tick=pattern.bar_range.start_bar * S1_BAR_TICKS,
                duration_tick=(pattern.bar_range.end_bar - pattern.bar_range.start_bar)
                * S1_BAR_TICKS,
                notes=_compile_pattern(project_id, pattern),
            )
            for pattern in role_patterns
        ),
    )


def build_s1_composition(project_id: UUID, *, seed: int) -> CompositionBuild:
    """Build the fixed S1 song as commands and replay them through the command path."""

    if not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be between 0 and 2^31-1")
    sections = _sections(project_id)
    patterns = _patterns(project_id, seed, sections)
    initialize = InitializeCompositionCommand(
        command_id=_stable_id(project_id, "command", seed, "initialize"),
        actor_kind="agent",
        client_sequence=0,
        selection=Selection(start_tick=0, end_tick=S1_DURATION_TICKS),
        payload=InitializeCompositionPayload(
            tempo=TempoPoint(bpm=S1_BPM),
            meter=MeterPoint(numerator=4, denominator=4),
            key_map=(
                KeyPoint(
                    tick=0,
                    tonic="C",
                    mode=MusicalMode.MAJOR,
                    confidence=1.0,
                    source=COMPOSER_VERSION,
                ),
            ),
            sections=sections,
            provenance=(
                ProvenanceRef(
                    kind="engine",
                    ref="motif-forge-deterministic-composer",
                    version=COMPOSER_VERSION,
                ),
            ),
        ),
    )
    track_commands = tuple(
        AddTrackCommand(
            command_id=_stable_id(project_id, "command", seed, "track", role),
            actor_kind="agent",
            client_sequence=index,
            selection=Selection(start_tick=0, end_tick=S1_DURATION_TICKS),
            payload=AddTrackPayload(track=_track(project_id, seed, role, patterns)),
        )
        for index, role in enumerate(PatternRole, start=1)
    )
    commands: tuple[EditorCommand, ...] = (initialize, *track_commands)
    arrangement = apply_commands(create_empty_arrangement(project_id), commands)
    issues = validate_s1_arrangement(arrangement)
    if issues:
        summary = "; ".join(f"{item.code}@{item.path}" for item in issues)
        raise ValueError(f"S1 composition failed validation: {summary}")
    return CompositionBuild(
        seed=seed,
        patterns=patterns,
        commands=commands,
        arrangement=arrangement,
        content_hash=arrangement_content_hash(arrangement),
        duration_seconds=float(ticks_to_seconds(arrangement.duration_tick, bpm=str(S1_BPM))),
    )


_MODE_INTERVALS: dict[MusicalMode, tuple[int, ...]] = {
    MusicalMode.MAJOR: (0, 2, 4, 5, 7, 9, 11),
    MusicalMode.MINOR: (0, 2, 3, 5, 7, 8, 10),
    MusicalMode.DORIAN: (0, 2, 3, 5, 7, 9, 10),
    MusicalMode.PHRYGIAN: (0, 1, 3, 5, 7, 8, 10),
    MusicalMode.LYDIAN: (0, 2, 4, 6, 7, 9, 11),
    MusicalMode.MIXOLYDIAN: (0, 2, 4, 5, 7, 9, 10),
    MusicalMode.LOCRIAN: (0, 1, 3, 5, 6, 8, 10),
}
_TONIC_PITCH_CLASS = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}
CanonicalTonic = Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_CANONICAL_TONIC: tuple[CanonicalTonic, ...] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)


def _plan_patterns(
    project_id: UUID, plan: CompositionPlan, seed: int, plan_hash: str
) -> tuple[PatternSpec, ...]:
    patterns: list[PatternSpec] = []
    for section_index, section in enumerate(plan.sections):
        bar_count = section.end_bar - section.start_bar
        energy_band = min(3, int(section.energy * 4))
        grids = {
            PatternRole.PAD: (0,),
            PatternRole.MELODY: (
                (0, 8),
                (0, 4, 8, 12),
                (0, 3, 6, 9, 12, 15),
                (0, 2, 4, 6, 8, 10, 12, 14),
            )[energy_band],
            PatternRole.BASS: ((0,), (0, 8), (0, 6, 12), (0, 4, 8, 12))[energy_band],
            PatternRole.RHYTHM: (
                (0, 8),
                (0, 4, 8, 12),
                (0, 2, 6, 8, 10, 14),
                (0, 2, 4, 6, 8, 10, 12, 14),
            )[energy_band],
        }
        for role_index, role in enumerate(PatternRole):
            variation_seed = (
                seed * 1_103 + section_index * 97 + role_index * 31 + energy_band * 17
            ) % (2**31)
            progression = tuple(
                ((section_index * 2 + bar + energy_band + variation_seed % 3) % 7) + 1
                for bar in range(bar_count)
            )
            patterns.append(
                PatternSpec(
                    pattern_id=_stable_id(
                        project_id,
                        "synth-ambient-pattern",
                        plan_hash,
                        seed,
                        section.section_id,
                        role,
                    ),
                    section_id=_stable_id(
                        project_id, "synth-ambient-section", plan_hash, section.section_id
                    ),
                    track_role=role,
                    bar_range=BarRange(start_bar=section.start_bar, end_bar=section.end_bar),
                    chord_degrees=progression,
                    rhythm_grid=grids[role],
                    register=_ROLE_REGISTER[role],
                    density=round(min(1.0, 0.15 + section.energy * 0.8), 6),
                    syncopation=(
                        round(section.energy * 0.3, 6)
                        if role in {PatternRole.MELODY, PatternRole.RHYTHM}
                        else 0.0
                    ),
                    variation_seed=variation_seed,
                    locked_constraints=(
                        f"key:{plan.key.tonic}-{plan.key.mode}",
                        "meter:4/4",
                        f"tempo:{plan.bpm}",
                        f"energy:{section.energy:.6f}",
                    ),
                )
            )
    return tuple(patterns)


def _pitch_for_degree(
    degree: int, *, tonic_pitch_class: int, intervals: tuple[int, ...], register: MidiRegister
) -> int:
    target_pitch_class = (tonic_pitch_class + intervals[(degree - 1) % 7]) % 12
    candidates = tuple(
        pitch
        for pitch in range(register.low_midi, register.high_midi + 1)
        if pitch % 12 == target_pitch_class
    )
    if not candidates:
        raise ValueError("the selected key cannot be realized inside the supported MIDI register")
    midpoint = (register.low_midi + register.high_midi) / 2
    return min(candidates, key=lambda pitch: (abs(pitch - midpoint), pitch))


def _compile_plan_pattern(
    project_id: UUID,
    pattern: PatternSpec,
    *,
    tonic_pitch_class: int,
    intervals: tuple[int, ...],
) -> tuple[NoteEvent, ...]:
    notes: list[NoteEvent] = []
    bar_count = pattern.bar_range.end_bar - pattern.bar_range.start_bar
    for bar_offset in range(bar_count):
        degree = pattern.chord_degrees[bar_offset]
        if pattern.track_role is PatternRole.PAD:
            for voice, degree_offset in enumerate((0, 2, 4)):
                pitch = _pitch_for_degree(
                    degree + degree_offset,
                    tonic_pitch_class=tonic_pitch_class,
                    intervals=intervals,
                    register=pattern.midi_register,
                )
                notes.append(
                    NoteEvent(
                        note_id=_stable_id(
                            project_id, pattern.pattern_id, "pad", bar_offset, voice
                        ),
                        pitch=pitch,
                        start_tick=bar_offset * S1_BAR_TICKS,
                        duration_tick=S1_BAR_TICKS - 60,
                        velocity=min(96, 48 + int(pattern.density * 28) + voice * 3),
                        articulation=Articulation.LEGATO,
                    )
                )
            continue

        for step_index, grid_step in enumerate(pattern.rhythm_grid):
            local_start = bar_offset * S1_BAR_TICKS + grid_step * (PPQ // 4)
            remaining_in_bar = (bar_offset + 1) * S1_BAR_TICKS - local_start
            if pattern.track_role is PatternRole.MELODY:
                selector = (pattern.variation_seed + bar_offset * 5 + step_index * 3) % 7
                pitch = _pitch_for_degree(
                    degree + selector,
                    tonic_pitch_class=tonic_pitch_class,
                    intervals=intervals,
                    register=pattern.midi_register,
                )
                duration = min(PPQ * 3 // 4, remaining_in_bar)
                velocity = min(112, 60 + int(pattern.density * 30) + selector % 4)
                articulation = Articulation.NORMAL
                label = "melody"
            elif pattern.track_role is PatternRole.BASS:
                pitch = _pitch_for_degree(
                    degree + (4 if step_index else 0),
                    tonic_pitch_class=tonic_pitch_class,
                    intervals=intervals,
                    register=pattern.midi_register,
                )
                duration = min(PPQ * 3 // 2, remaining_in_bar)
                velocity = min(112, 62 + int(pattern.density * 28))
                articulation = Articulation.NORMAL
                label = "bass"
            else:
                pitch = 36
                duration = min(PPQ // 8, remaining_in_bar)
                velocity = 88 if grid_step == 0 else min(82, 52 + int(pattern.density * 26))
                articulation = Articulation.STACCATO
                label = "rhythm"
            notes.append(
                NoteEvent(
                    note_id=_stable_id(
                        project_id, pattern.pattern_id, label, bar_offset, step_index
                    ),
                    pitch=pitch,
                    start_tick=local_start,
                    duration_tick=duration,
                    velocity=velocity,
                    articulation=articulation,
                )
            )
    return tuple(notes)


def _plan_track(
    project_id: UUID,
    *,
    plan_hash: str,
    seed: int,
    role: PatternRole,
    patterns: tuple[PatternSpec, ...],
    tonic_pitch_class: int,
    intervals: tuple[int, ...],
) -> Track:
    role_patterns = tuple(pattern for pattern in patterns if pattern.track_role is role)
    return Track(
        track_id=_stable_id(project_id, "synth-ambient-track", plan_hash, role),
        track_type=TrackType.INSTRUMENT,
        name=_TRACK_NAMES[role],
        role=_ROLE_TO_TRACK_ROLE[role],
        gain_db=-6.0 if role is PatternRole.PAD else -4.0,
        pan=-0.12 if role is PatternRole.PAD else (0.12 if role is PatternRole.MELODY else 0.0),
        instrument_ref=_INSTRUMENTS[role],
        clips=tuple(
            NoteClip(
                clip_id=_stable_id(
                    project_id, "synth-ambient-clip", plan_hash, seed, pattern.section_id, role
                ),
                start_tick=pattern.bar_range.start_bar * S1_BAR_TICKS,
                duration_tick=(pattern.bar_range.end_bar - pattern.bar_range.start_bar)
                * S1_BAR_TICKS,
                notes=_compile_plan_pattern(
                    project_id,
                    pattern,
                    tonic_pitch_class=tonic_pitch_class,
                    intervals=intervals,
                ),
            )
            for pattern in role_patterns
        ),
    )


def compile_synth_ambient_plan(
    project_id: UUID, *, plan: CompositionPlan, seed: int
) -> CompositionBuild:
    """Compile one validated Synth Ambient plan through audited editor commands."""

    if not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be between 0 and 2^31-1")
    if plan.genre != "synth_ambient" or plan.meter != "4/4":
        raise ValueError("Synth Ambient compilation requires a synth_ambient 4/4 plan")
    roles = tuple(sorted(item.role.casefold().strip() for item in plan.instrumentation))
    if roles != ("bass", "melody", "pad", "rhythm"):
        raise ValueError("Synth Ambient compilation requires one supported instrument per role")
    if any(section.end_bar - section.start_bar > 32 for section in plan.sections):
        raise ValueError("Synth Ambient sections cannot exceed the PatternSpec v1 bar limit")

    duration_seconds = plan.duration_bars * 4 * 60 / plan.bpm
    if duration_seconds > 300:
        raise ValueError("compiled composition duration exceeds the first-release limit")
    plan_hash = composition_plan_content_hash(plan)
    mode = MusicalMode(plan.key.mode)
    tonic_pitch_class = _TONIC_PITCH_CLASS[plan.key.tonic]
    intervals = _MODE_INTERVALS[mode]
    sections = tuple(
        Section(
            section_id=_stable_id(
                project_id, "synth-ambient-section", plan_hash, section.section_id
            ),
            start_tick=section.start_bar * S1_BAR_TICKS,
            end_tick=section.end_bar * S1_BAR_TICKS,
            label=section.name,
            function=section.function,
            energy=section.energy,
        )
        for section in plan.sections
    )
    patterns = _plan_patterns(project_id, plan, seed, plan_hash)
    initialize = InitializeCompositionCommand(
        command_id=_stable_id(project_id, "synth-ambient-command", plan_hash, seed, "initialize"),
        actor_kind="agent",
        client_sequence=0,
        selection=Selection(start_tick=0, end_tick=plan.duration_bars * S1_BAR_TICKS),
        payload=InitializeCompositionPayload(
            tempo=TempoPoint(bpm=float(plan.bpm)),
            meter=MeterPoint(numerator=4, denominator=4),
            key_map=(
                KeyPoint(
                    tick=0,
                    tonic=_CANONICAL_TONIC[tonic_pitch_class],
                    mode=mode,
                    confidence=plan.confidence,
                    source=SYNTH_AMBIENT_COMPILER_VERSION,
                ),
            ),
            sections=sections,
            provenance=(
                ProvenanceRef(
                    kind="knowledge",
                    ref=f"composition-plan:{plan_hash}",
                    version=plan.schema_version,
                ),
                ProvenanceRef(
                    kind="engine",
                    ref="motif-forge-synth-ambient-compiler",
                    version=SYNTH_AMBIENT_COMPILER_VERSION,
                ),
                ProvenanceRef(
                    kind="knowledge",
                    ref="style-pack:synth-ambient",
                    version="synth-ambient.v1",
                ),
            ),
        ),
    )
    track_commands = tuple(
        AddTrackCommand(
            command_id=_stable_id(
                project_id, "synth-ambient-command", plan_hash, seed, "track", role
            ),
            actor_kind="agent",
            client_sequence=index,
            selection=Selection(start_tick=0, end_tick=plan.duration_bars * S1_BAR_TICKS),
            payload=AddTrackPayload(
                track=_plan_track(
                    project_id,
                    plan_hash=plan_hash,
                    seed=seed,
                    role=role,
                    patterns=patterns,
                    tonic_pitch_class=tonic_pitch_class,
                    intervals=intervals,
                )
            ),
        )
        for index, role in enumerate(PatternRole, start=1)
    )
    commands: tuple[EditorCommand, ...] = (initialize, *track_commands)
    arrangement = apply_commands(create_empty_arrangement(project_id), commands)
    return CompositionBuild(
        seed=seed,
        patterns=patterns,
        commands=commands,
        arrangement=arrangement,
        content_hash=arrangement_content_hash(arrangement),
        duration_seconds=float(duration_seconds),
    )


def _maximum_polyphony(clip: NoteClip) -> int:
    events = chain.from_iterable(
        ((note.start_tick, 1), (note.start_tick + note.duration_tick, -1)) for note in clip.notes
    )
    active = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def validate_s1_arrangement(arrangement: ArrangementIR) -> tuple[DomainIssue, ...]:
    """Return stable S1 walking-skeleton issues without invoking a model."""

    issues: list[DomainIssue] = []
    if arrangement.duration_tick != S1_DURATION_TICKS or len(arrangement.sections) != 4:
        issues.append(
            DomainIssue(
                code="S1_FORM_INVALID",
                path="sections",
                message="S1 requires four contiguous sections across 24 bars",
            )
        )
    if arrangement.tempo_map[0].bpm != S1_BPM:
        issues.append(
            DomainIssue(code="S1_TEMPO_INVALID", path="tempo_map", message="S1 requires 80 BPM")
        )
    if len(arrangement.tracks) != 4:
        issues.append(
            DomainIssue(
                code="S1_TRACK_COUNT_INVALID",
                path="tracks",
                message="S1 requires exactly four tracks",
            )
        )
    role_ranges = {
        TrackRole.HARMONY: (48, 72, "S1_PAD_RANGE_INVALID", 8),
        TrackRole.MELODY: (60, 84, "S1_MELODY_RANGE_INVALID", 4),
        TrackRole.BASS: (36, 52, "S1_BASS_RANGE_INVALID", 2),
        TrackRole.RHYTHM: (36, 36, "S1_RHYTHM_RANGE_INVALID", 4),
    }
    seen_roles: set[TrackRole] = set()
    for track in arrangement.tracks:
        definition = role_ranges.get(track.role)
        if definition is None or track.role in seen_roles:
            issues.append(
                DomainIssue(
                    code="S1_TRACK_ROLE_INVALID",
                    path=f"tracks.{track.track_id}.role",
                    message="S1 requires one harmony, melody, bass and rhythm track",
                )
            )
            continue
        seen_roles.add(track.role)
        low, high, range_code, max_polyphony = definition
        for clip in track.clips:
            if not isinstance(clip, NoteClip):
                issues.append(
                    DomainIssue(
                        code="S1_CLIP_TYPE_INVALID",
                        path=f"tracks.{track.track_id}.clips.{clip.clip_id}",
                        message="S1 deterministic tracks require NoteClip material",
                    )
                )
                continue
            for note in clip.notes:
                if not low <= note.pitch <= high:
                    issues.append(
                        DomainIssue(
                            code=range_code,
                            path=f"tracks.{track.track_id}.clips.{clip.clip_id}.notes.{note.note_id}",
                            message=f"note must remain within MIDI {low}-{high}",
                        )
                    )
            if _maximum_polyphony(clip) > max_polyphony:
                issues.append(
                    DomainIssue(
                        code="S1_POLYPHONY_INVALID",
                        path=f"tracks.{track.track_id}.clips.{clip.clip_id}",
                        message=f"track exceeds S1 polyphony limit {max_polyphony}",
                    )
                )
    if seen_roles != set(role_ranges):
        issues.append(
            DomainIssue(
                code="S1_TRACK_ROLE_SET_INVALID",
                path="tracks",
                message="S1 track role set is incomplete",
            )
        )
    return tuple(sorted(issues, key=lambda item: (item.path, item.code)))
