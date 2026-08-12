"""Pure, versioned music-domain models for Motif Forge."""

from __future__ import annotations

from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal, Self
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


def create_empty_arrangement(project_id: UUID) -> ArrangementIR:
    """Create the canonical, writable empty project arrangement."""

    return ArrangementIR(project_id=project_id)
