"""Pure, versioned music-domain models for Motif Forge."""

from __future__ import annotations

import json
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

IR_SCHEMA_VERSION = "arrangement-ir.v1"
PPQ = 480
MAX_TRACKS = 12
ALLOWED_SAMPLE_RATES = frozenset({44_100, 48_000, 96_000})


class DomainModel(BaseModel):
    """Strict value object shared by all pure domain schemas."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TrackType(StrEnum):
    INSTRUMENT = "instrument"
    AUDIO = "audio"
    BUS = "bus"


class TrackRole(StrEnum):
    MELODY = "melody"
    HARMONY = "harmony"
    BASS = "bass"
    RHYTHM = "rhythm"
    TEXTURE = "texture"
    FX = "fx"
    OTHER = "other"


class Articulation(StrEnum):
    NORMAL = "normal"
    LEGATO = "legato"
    STACCATO = "staccato"
    TENUTO = "tenuto"
    ACCENT = "accent"


class AudioSourceKind(StrEnum):
    IMPORTED = "imported"
    SAMPLE = "sample"
    GENERATED = "generated"


class MusicalMode(StrEnum):
    MAJOR = "major"
    MINOR = "minor"
    DORIAN = "dorian"
    PHRYGIAN = "phrygian"
    LYDIAN = "lydian"
    MIXOLYDIAN = "mixolydian"
    LOCRIAN = "locrian"


class TempoPoint(DomainModel):
    tick: Literal[0] = 0
    bpm: float = Field(ge=20.0, le=300.0, allow_inf_nan=False)


class MeterPoint(DomainModel):
    tick: Literal[0] = 0
    numerator: Literal[3, 4] = 4
    denominator: Literal[4] = 4


class KeyPoint(DomainModel):
    tick: int = Field(ge=0)
    tonic: Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    mode: MusicalMode
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    source: str = Field(min_length=1, max_length=80)


class Section(DomainModel):
    section_id: UUID
    start_tick: int = Field(ge=0)
    end_tick: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=80)
    function: str = Field(default="unspecified", min_length=1, max_length=80)
    energy: float = Field(default=0.5, ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_tick <= self.start_tick:
            raise ValueError("section end_tick must be greater than start_tick")
        return self


class Marker(DomainModel):
    marker_id: UUID
    tick: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["user", "system"] = "user"


class Equalizer3Band(DomainModel):
    low_db: float = Field(default=0.0, ge=-24.0, le=24.0, allow_inf_nan=False)
    mid_db: float = Field(default=0.0, ge=-24.0, le=24.0, allow_inf_nan=False)
    high_db: float = Field(default=0.0, ge=-24.0, le=24.0, allow_inf_nan=False)


class NoteEvent(DomainModel):
    note_id: UUID
    pitch: int = Field(ge=0, le=127)
    start_tick: int = Field(ge=0)
    duration_tick: int = Field(gt=0)
    velocity: int = Field(default=100, ge=1, le=127)
    articulation: Articulation = Articulation.NORMAL
    cents: float = Field(default=0.0, ge=-100.0, le=100.0, allow_inf_nan=False)


class NoteClip(DomainModel):
    clip_type: Literal["note"] = "note"
    clip_id: UUID
    start_tick: int = Field(ge=0)
    duration_tick: int = Field(gt=0)
    loop: bool = False
    gain_db: float = Field(default=0.0, ge=-60.0, le=12.0, allow_inf_nan=False)
    pan: float = Field(default=0.0, ge=-1.0, le=1.0, allow_inf_nan=False)
    fade_in_tick: int = Field(default=0, ge=0)
    fade_out_tick: int = Field(default=0, ge=0)
    notes: tuple[NoteEvent, ...] = ()

    @model_validator(mode="after")
    def validate_notes(self) -> Self:
        if self.fade_in_tick + self.fade_out_tick > self.duration_tick:
            raise ValueError("clip fades cannot exceed clip duration")
        note_ids: set[UUID] = set()
        for note in self.notes:
            if note.note_id in note_ids:
                raise ValueError("note_id must be unique within a clip")
            note_ids.add(note.note_id)
            if note.start_tick + note.duration_tick > self.duration_tick:
                raise ValueError("note must remain within its clip")
        return self


class TimeStretchRef(DomainModel):
    artifact_id: UUID
    source_artifact_id: UUID
    preserve_pitch: Literal[True] = True
    ratio: float = Field(gt=0.0, le=8.0, allow_inf_nan=False)
    source_bpm: float = Field(ge=20.0, le=300.0, allow_inf_nan=False)
    target_bpm: float = Field(ge=20.0, le=300.0, allow_inf_nan=False)
    engine_version: str = Field(min_length=1, max_length=80)


class AudioClip(DomainModel):
    clip_type: Literal["audio"] = "audio"
    clip_id: UUID
    source_kind: AudioSourceKind
    artifact_id: UUID
    start_tick: int = Field(ge=0)
    duration_tick: int = Field(gt=0)
    source_offset_seconds: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    source_duration_seconds: float = Field(gt=0.0, allow_inf_nan=False)
    source_bpm: float | None = Field(default=None, ge=20.0, le=300.0, allow_inf_nan=False)
    target_bpm: float | None = Field(default=None, ge=20.0, le=300.0, allow_inf_nan=False)
    transpose_semitones: int = Field(default=0, ge=-24, le=24)
    time_stretch_ref: TimeStretchRef | None = None
    loop: bool = False
    gain_db: float = Field(default=0.0, ge=-60.0, le=12.0, allow_inf_nan=False)
    pan: float = Field(default=0.0, ge=-1.0, le=1.0, allow_inf_nan=False)
    fade_in_tick: int = Field(default=0, ge=0)
    fade_out_tick: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_audio_clip(self) -> Self:
        if self.fade_in_tick + self.fade_out_tick > self.duration_tick:
            raise ValueError("clip fades cannot exceed clip duration")
        if (self.source_bpm is None) != (self.target_bpm is None):
            raise ValueError("source_bpm and target_bpm must be provided together")
        return self


Clip = Annotated[NoteClip | AudioClip, Field(discriminator="clip_type")]


class LockedRange(DomainModel):
    start_tick: int = Field(ge=0)
    end_tick: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_tick <= self.start_tick:
            raise ValueError("locked range end_tick must be greater than start_tick")
        return self


class Track(DomainModel):
    track_id: UUID
    track_type: TrackType
    name: str = Field(min_length=1, max_length=80)
    role: TrackRole = TrackRole.OTHER
    mute: bool = False
    solo: bool = False
    gain_db: float = Field(default=0.0, ge=-60.0, le=12.0, allow_inf_nan=False)
    pan: float = Field(default=0.0, ge=-1.0, le=1.0, allow_inf_nan=False)
    eq: Equalizer3Band = Field(default_factory=Equalizer3Band)
    instrument_ref: str | None = Field(default=None, min_length=1, max_length=160)
    clips: tuple[Clip, ...] = ()
    locked_ranges: tuple[LockedRange, ...] = ()

    @model_validator(mode="after")
    def validate_track_contents(self) -> Self:
        clip_ids: set[UUID] = set()
        for clip in self.clips:
            if clip.clip_id in clip_ids:
                raise ValueError("clip_id must be unique within a track")
            clip_ids.add(clip.clip_id)
            if self.track_type is TrackType.INSTRUMENT and not isinstance(clip, NoteClip):
                raise ValueError("instrument tracks accept only note clips")
            if self.track_type is TrackType.AUDIO and not isinstance(clip, AudioClip):
                raise ValueError("audio tracks accept only audio clips")
            if self.track_type is TrackType.BUS:
                raise ValueError("bus tracks cannot contain clips")
        ordered_locks = sorted(
            self.locked_ranges, key=lambda item: (item.start_tick, item.end_tick)
        )
        for previous, current in pairwise(ordered_locks):
            if current.start_tick < previous.end_tick:
                raise ValueError("locked ranges cannot overlap")
        return self


class RoutingSpec(DomainModel):
    master_bus: Literal["master"] = "master"


class ProvenanceRef(DomainModel):
    kind: Literal["human", "model", "knowledge", "asset", "engine"]
    ref: str = Field(min_length=1, max_length=200)
    version: str | None = Field(default=None, min_length=1, max_length=80)


class ArrangementIR(DomainModel):
    schema_version: Literal["arrangement-ir.v1"] = "arrangement-ir.v1"
    project_id: UUID
    sample_rate: Literal[44_100, 48_000, 96_000] = 48_000
    ppq: Literal[480] = 480
    tempo_map: tuple[TempoPoint, ...] = Field(default_factory=lambda: (TempoPoint(bpm=120.0),))
    time_signature_map: tuple[MeterPoint, ...] = Field(default_factory=lambda: (MeterPoint(),))
    key_map: tuple[KeyPoint, ...] = ()
    sections: tuple[Section, ...] = ()
    markers: tuple[Marker, ...] = ()
    tracks: tuple[Track, ...] = ()
    routing: RoutingSpec = Field(default_factory=RoutingSpec)
    provenance: tuple[ProvenanceRef, ...] = ()

    @property
    def duration_tick(self) -> int:
        return max((section.end_tick for section in self.sections), default=0)

    @property
    def bar_ticks(self) -> int:
        meter = self.time_signature_map[0]
        return self.ppq * meter.numerator * 4 // meter.denominator

    @model_validator(mode="after")
    def validate_arrangement(self) -> Self:
        if self.sample_rate not in ALLOWED_SAMPLE_RATES:
            raise ValueError("sample_rate is not supported")
        if len(self.tempo_map) != 1 or self.tempo_map[0].tick != 0:
            raise ValueError("v1 requires exactly one global tempo point at tick 0")
        if len(self.time_signature_map) != 1 or self.time_signature_map[0].tick != 0:
            raise ValueError("v1 requires exactly one global meter point at tick 0")
        if len(self.tracks) > MAX_TRACKS:
            raise ValueError("v1 supports at most 12 tracks")

        sections = sorted(self.sections, key=lambda item: (item.start_tick, str(item.section_id)))
        if sections:
            if sections[0].start_tick != 0:
                raise ValueError("sections must start at tick 0")
            expected_start = 0
            for section in sections:
                if section.start_tick != expected_start:
                    raise ValueError("sections must be contiguous and non-overlapping")
                if section.start_tick % self.bar_ticks or section.end_tick % self.bar_ticks:
                    raise ValueError("section boundaries must align to whole bars")
                expected_start = section.end_tick

        track_ids: set[UUID] = set()
        clip_ids: set[UUID] = set()
        for track in self.tracks:
            if track.track_id in track_ids:
                raise ValueError("track_id must be unique")
            track_ids.add(track.track_id)
            for clip in track.clips:
                if clip.clip_id in clip_ids:
                    raise ValueError("clip_id must be unique across the arrangement")
                clip_ids.add(clip.clip_id)
                if not sections:
                    raise ValueError("clips require at least one section to define project bounds")
                if clip.start_tick + clip.duration_tick > self.duration_tick:
                    raise ValueError("clip must remain within arrangement bounds")
            for locked_range in track.locked_ranges:
                if not sections or locked_range.end_tick > self.duration_tick:
                    raise ValueError("locked range must remain within arrangement bounds")

        section_starts = {section.start_tick for section in sections}
        key_ticks: set[int] = set()
        for key_point in self.key_map:
            if key_point.tick in key_ticks:
                raise ValueError("key points must use unique ticks")
            key_ticks.add(key_point.tick)
            if not sections or key_point.tick not in section_starts:
                raise ValueError("key changes must align to section starts")

        marker_ids: set[UUID] = set()
        for marker in self.markers:
            if marker.marker_id in marker_ids:
                raise ValueError("marker_id must be unique")
            marker_ids.add(marker.marker_id)
            if not sections or marker.tick > self.duration_tick:
                raise ValueError("markers require sections and must remain within project bounds")
        return self


class PianoRenderProfile(DomainModel):
    """One approved, immutable C1 source; no paths or arbitrary URLs in project data."""

    schema_version: Literal["render-profile.v1"] = "render-profile.v1"
    engine_version: Literal["motif-forge-audio-engine.v2"] = "motif-forge-audio-engine.v2"
    instrument_pack_id: Literal["freepats:upright-kw-small"] = "freepats:upright-kw-small"
    instrument_pack_version: Literal["2019-07-03.motif1"] = "2019-07-03.motif1"
    manifest_sha256: Literal["264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813"] = (
        "264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813"
    )


class NotePerformance(DomainModel):
    track_id: UUID
    clip_id: UUID
    note_id: UUID
    onset_offset_tick: int = Field(default=0, ge=-60, le=60)
    velocity_override: int | None = Field(default=None, ge=1, le=127)
    gate_duration_tick: int | None = Field(default=None, ge=1, le=9600)


class PedalEvent(DomainModel):
    tick: int = Field(ge=0)
    value: Literal[0, 127]


class PerformancePlan(DomainModel):
    schema_version: Literal["performance-plan.v1"] = "performance-plan.v1"
    notes: tuple[NotePerformance, ...] = Field(default=(), max_length=2000)
    pedal_events: tuple[PedalEvent, ...] = ()

    @model_validator(mode="after")
    def validate_events(self) -> Self:
        if self.pedal_events:
            raise ValueError("PIANO_PEDAL_UNSUPPORTED")
        ids = [(item.track_id, item.clip_id, item.note_id) for item in self.notes]
        if len(ids) != len(set(ids)):
            raise ValueError("PERFORMANCE_NOTE_DUPLICATE")
        return self


class ArrangementIRV2(ArrangementIR):
    schema_version: Literal["arrangement-ir.v2"] = "arrangement-ir.v2"  # type: ignore[assignment]
    render_profile: PianoRenderProfile
    performance_plan: PerformancePlan = Field(default_factory=PerformancePlan)

    @model_validator(mode="after")
    def validate_piano_performance(self) -> Self:
        return _validate_piano_performance(self, maximum_tracks=1)


class EnsemblePianoRenderProfile(PianoRenderProfile):
    engine_version: Literal["motif-forge-audio-engine.v3"] = "motif-forge-audio-engine.v3"  # type: ignore[assignment]


class ArrangementIRV3(ArrangementIRV2):
    """Explicit two-part piano arrangement; v2 keeps its single-track contract."""

    schema_version: Literal["arrangement-ir.v3"] = "arrangement-ir.v3"  # type: ignore[assignment]
    render_profile: EnsemblePianoRenderProfile

    @model_validator(mode="after")
    def validate_piano_performance(self) -> Self:
        return _validate_piano_performance(self, maximum_tracks=2)


def _validate_piano_performance[T: ArrangementIRV2](arrangement: T, *, maximum_tracks: int) -> T:
    if not 1 <= len(arrangement.tracks) <= maximum_tracks or any(
        t.track_type is not TrackType.INSTRUMENT for t in arrangement.tracks
    ):
        raise ValueError("PIANO_SINGLE_TRACK_REQUIRED")
    if arrangement.sample_rate != 48000:
        raise ValueError("PIANO_SAMPLE_RATE_UNSUPPORTED")
    facts = {}
    for track in arrangement.tracks:
        for clip in track.clips:
            if not isinstance(clip, NoteClip):
                raise ValueError("PIANO_NOTE_CLIP_REQUIRED")
            if (
                clip.loop
                or clip.gain_db != 0
                or clip.pan != 0
                or clip.fade_in_tick
                or clip.fade_out_tick
            ):
                raise ValueError("PIANO_CLIP_PARAMETERS_UNSUPPORTED")
            for note in clip.notes:
                if note.articulation is not Articulation.NORMAL:
                    raise ValueError("PIANO_ARTICULATION_UNSUPPORTED")
                if not 21 <= note.pitch <= 108:
                    raise ValueError("PIANO_KEY_RANGE_UNSUPPORTED")
                facts[track.track_id, clip.clip_id, note.note_id] = (clip, note)
    if len(facts) > 2000:
        raise ValueError("PIANO_NOTE_BUDGET_EXCEEDED")
    overrides = {
        (item.track_id, item.clip_id, item.note_id): item
        for item in arrangement.performance_plan.notes
    }
    if not overrides.keys() <= facts.keys():
        raise ValueError("PERFORMANCE_NOTE_NOT_FOUND")
    seconds_per_tick = 60 / arrangement.tempo_map[0].bpm / arrangement.ppq
    for identity, (clip, note) in facts.items():
        performance = overrides.get(identity)
        start = (
            clip.start_tick
            + note.start_tick
            + (performance.onset_offset_tick if performance else 0)
        )
        if start < 0 or start >= arrangement.duration_tick:
            raise ValueError("PERFORMANCE_ONSET_OUT_OF_BOUNDS")
        gate = (
            performance.gate_duration_tick
            if performance and performance.gate_duration_tick is not None
            else note.duration_tick
        )
        if (
            not 0.005 <= gate * seconds_per_tick <= 30
            or (start + gate) * seconds_per_tick + 0.6
            > arrangement.duration_tick * seconds_per_tick + 1e-6
        ):
            raise ValueError("PERFORMANCE_GATE_OUT_OF_BOUNDS")
    return arrangement


class PianoTrackMix(DomainModel):
    track_id: UUID
    gain_db: float = Field(default=0.0, ge=-60.0, le=6.0, allow_inf_nan=False)
    pan: float = Field(default=0.0, ge=-1.0, le=1.0, allow_inf_nan=False)
    mute: bool = False
    solo: bool = False


class PianoMixState(DomainModel):
    schema_version: Literal["piano-mix.v1"] = "piano-mix.v1"
    tracks: tuple[PianoTrackMix, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_tracks(self) -> Self:
        if len({item.track_id for item in self.tracks}) != len(self.tracks):
            raise ValueError("PIANO_MIX_TRACKS_INVALID")
        return self


class MixPianoRenderProfile(EnsemblePianoRenderProfile):
    engine_version: Literal["motif-forge-audio-engine.v4"] = "motif-forge-audio-engine.v4"  # type: ignore[assignment]


class ArrangementIRV4(ArrangementIRV3):
    schema_version: Literal["arrangement-ir.v4"] = "arrangement-ir.v4"  # type: ignore[assignment]
    render_profile: MixPianoRenderProfile
    piano_mix: PianoMixState

    @model_validator(mode="after")
    def validate_mix(self) -> Self:
        if len(self.tracks) != 2:
            raise ValueError("PIANO_MIX_PROFILE_UNSUPPORTED")
        if {item.track_id for item in self.piano_mix.tracks} != {t.track_id for t in self.tracks}:
            raise ValueError("PIANO_MIX_TRACKS_INVALID")
        if any(
            not -60 <= t.gain_db <= 6
            or any(abs(value) > 12 for value in (t.eq.low_db, t.eq.mid_db, t.eq.high_db))
            for t in self.tracks
        ):
            raise ValueError("PIANO_MIX_LEGACY_RANGE")
        return self


class PianoEqProfile(DomainModel):
    schema_version: Literal["three-band-eq-profile.v1"] = "three-band-eq-profile.v1"
    profile_id: Literal["motif-three-band-static.v1"] = "motif-three-band-static.v1"
    sample_rate_hz: Literal[48000] = 48000
    low_frequency_hz: Literal[180] = 180
    mid_frequency_hz: Literal[1000] = 1000
    mid_q: Literal[0.8] = 0.8  # type: ignore[valid-type]
    high_frequency_hz: Literal[6000] = 6000
    shelf_slope: Literal[1.0] = 1.0  # type: ignore[valid-type]

    @model_validator(mode="before")
    @classmethod
    def strict_profile_numbers(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(
            key in value and type(value[key]) not in (int, float)
            for key in (
                "sample_rate_hz",
                "low_frequency_hz",
                "mid_frequency_hz",
                "mid_q",
                "high_frequency_hz",
                "shelf_slope",
            )
        ):
            raise ValueError("PIANO_EQ_PROFILE_INVALID")
        return value


class PianoTrackEq(DomainModel):
    track_id: UUID
    schema_version: Literal["piano-eq.v1"] = "piano-eq.v1"
    profile_id: Literal["motif-three-band-static.v1"] = "motif-three-band-static.v1"
    bypass: bool = False
    low_gain_db: float = Field(default=0.0, ge=-12.0, le=12.0, allow_inf_nan=False)
    mid_gain_db: float = Field(default=0.0, ge=-12.0, le=12.0, allow_inf_nan=False)
    high_gain_db: float = Field(default=0.0, ge=-12.0, le=12.0, allow_inf_nan=False)


class PianoEqState(DomainModel):
    schema_version: Literal["piano-eq-state.v1"] = "piano-eq-state.v1"
    tracks: tuple[PianoTrackEq, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def unique_tracks(self) -> Self:
        if len({item.track_id for item in self.tracks}) != 2:
            raise ValueError("PIANO_EQ_TRACKS_INVALID")
        return self


class EqPianoRenderProfile(MixPianoRenderProfile):
    engine_version: Literal["motif-forge-audio-engine.v5"] = "motif-forge-audio-engine.v5"  # type: ignore[assignment]
    eq_profile: PianoEqProfile


class ArrangementIRV5(ArrangementIRV4):
    schema_version: Literal["arrangement-ir.v5"] = "arrangement-ir.v5"  # type: ignore[assignment]
    render_profile: EqPianoRenderProfile
    piano_eq: PianoEqState

    @model_validator(mode="after")
    def validate_eq(self) -> Self:
        if {item.track_id for item in self.piano_eq.tracks} != {t.track_id for t in self.tracks}:
            raise ValueError("PIANO_EQ_TRACKS_INVALID")
        return self


ArrangementValue = Annotated[
    ArrangementIR | ArrangementIRV2 | ArrangementIRV3 | ArrangementIRV4 | ArrangementIRV5,
    Field(discriminator="schema_version"),
]


def read_arrangement_json(
    value: str | bytes, *, strict: Literal[True] = True
) -> ArrangementIR | ArrangementIRV2 | ArrangementIRV3 | ArrangementIRV4 | ArrangementIRV5:
    data: Any = json.loads(value)
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version == "arrangement-ir.v1":
        return ArrangementIR.model_validate_json(value, strict=strict)
    if version == "arrangement-ir.v2":
        return ArrangementIRV2.model_validate_json(value, strict=strict)
    if version == "arrangement-ir.v3":
        return ArrangementIRV3.model_validate_json(value, strict=strict)
    if version == "arrangement-ir.v4":
        return ArrangementIRV4.model_validate_json(value, strict=strict)
    if version == "arrangement-ir.v5":
        return ArrangementIRV5.model_validate_json(value, strict=strict)
    raise ValueError("IR_SCHEMA_VERSION_UNSUPPORTED")


def create_empty_arrangement(project_id: UUID) -> ArrangementIR:
    """Create the canonical, writable empty project arrangement."""

    return ArrangementIR(project_id=project_id)
