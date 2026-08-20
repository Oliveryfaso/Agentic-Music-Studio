"""Strict schemas at the first AI planning boundary.

These objects intentionally describe musical intent, not note events or audio samples.
The downstream deterministic music compiler owns realization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, NotRequired, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

StyleId = Literal[
    "synth_ambient",
    "minimal_electronic",
    "classical_chamber",
    "jazz_harmony_improvisation",
]
Meter = Literal["4/4", "3/4"]
Mode = Literal[
    "major",
    "minor",
    "dorian",
    "phrygian",
    "lydian",
    "mixolydian",
    "locrian",
]

NonEmptyText = Annotated[str, Field(min_length=1, max_length=240)]
ShortText = Annotated[str, Field(min_length=1, max_length=80)]


class StrictSchema(BaseModel):
    """Base contract that rejects coercion and unknown model output."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class CompositionBrief(StrictSchema):
    """User-approved inputs for macro composition planning."""

    schema_version: Literal["composition-brief.v1"] = "composition-brief.v1"
    title: ShortText
    purpose: NonEmptyText
    style: StyleId
    duration_seconds: Annotated[int, Field(ge=60, le=300)]
    meter: Meter = "4/4"
    target_bpm: Annotated[int, Field(ge=40, le=220)] | None = None
    target_key: ShortText | None = None
    moods: tuple[ShortText, ...] = Field(min_length=1, max_length=6)
    preferred_instruments: tuple[ShortText, ...] = Field(default=(), max_length=12)
    hard_constraints: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)
    soft_preferences: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)
    negative_constraints: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def instrumental_only(self) -> CompositionBrief:
        forbidden_terms = ("vocal", "vocals", "voice clone", "singing", "人声", "演唱")
        searchable = " ".join((self.purpose, *self.hard_constraints)).casefold()
        if any(term in searchable for term in forbidden_terms):
            raise ValueError("the first release supports instrumental music only")
        return self


class SectionAdjustment(StrictSchema):
    name: ShortText
    bars: Annotated[int, Field(ge=1, le=128)]
    energy: Annotated[float, Field(ge=0.0, le=1.0)]


class InstrumentAdjustment(StrictSchema):
    name: ShortText
    role: ShortText


class PlanAdjustment(StrictSchema):
    """Human-authored intent for one immutable child planning Run."""

    schema_version: Literal["plan-adjustment.v1"] = "plan-adjustment.v1"
    target_bpm: Annotated[int, Field(ge=40, le=220)] | None = None
    target_key: ShortText | None = None
    sections: tuple[SectionAdjustment, ...] | None = Field(
        default=None, min_length=2, max_length=12
    )
    instrumentation: tuple[InstrumentAdjustment, ...] | None = Field(
        default=None, min_length=1, max_length=12
    )
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_adjustment(self) -> PlanAdjustment:
        if not any(
            (
                self.target_bpm is not None,
                self.target_key is not None,
                self.sections is not None,
                self.instrumentation is not None,
                bool(self.note),
            )
        ):
            raise ValueError("at least one Plan adjustment field must change")
        if self.sections is not None:
            total_bars = sum(section.bars for section in self.sections)
            if not 8 <= total_bars <= 256:
                raise ValueError("adjusted sections must total between 8 and 256 bars")
        return self


class KeyPlan(StrictSchema):
    tonic: Literal[
        "C",
        "C#",
        "Db",
        "D",
        "D#",
        "Eb",
        "E",
        "F",
        "F#",
        "Gb",
        "G",
        "G#",
        "Ab",
        "A",
        "A#",
        "Bb",
        "B",
    ]
    mode: Mode


class SectionPlan(StrictSchema):
    section_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    name: ShortText
    start_bar: Annotated[int, Field(ge=0)]
    end_bar: Annotated[int, Field(gt=0)]
    function: NonEmptyText
    energy: Annotated[float, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def positive_range(self) -> SectionPlan:
        if self.end_bar <= self.start_bar:
            raise ValueError("section end_bar must be greater than start_bar")
        return self


class InstrumentPlan(StrictSchema):
    instrument_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    name: ShortText
    role: ShortText
    pitch_range: ShortText
    entry_section_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    exit_section_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class KnowledgeReference(StrictSchema):
    reference_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:/-]{1,160}$")]
    summary: NonEmptyText
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class CompositionPlan(StrictSchema):
    """Validated macro plan produced by the CompositionPlanner."""

    schema_version: Literal["composition-plan.v1"] = "composition-plan.v1"
    genre: StyleId
    era_influences: tuple[ShortText, ...] = Field(default=(), max_length=6)
    purpose: NonEmptyText
    moods: tuple[ShortText, ...] = Field(min_length=1, max_length=6)
    duration_bars: Annotated[int, Field(ge=8, le=256)]
    bpm: Annotated[int, Field(ge=40, le=220)]
    meter: Meter
    key: KeyPlan
    sections: tuple[SectionPlan, ...] = Field(min_length=2, max_length=24)
    instrumentation: tuple[InstrumentPlan, ...] = Field(min_length=1, max_length=12)
    harmonic_language: NonEmptyText
    rhythmic_language: NonEmptyText
    texture: NonEmptyText
    hard_constraints: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)
    soft_preferences: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)
    negative_constraints: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)
    knowledge_references: tuple[KnowledgeReference, ...] = Field(default=(), max_length=12)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def validate_structure(self) -> CompositionPlan:
        section_ids = [section.section_id for section in self.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("section_id values must be unique")
        instrument_ids = [item.instrument_id for item in self.instrumentation]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("instrument_id values must be unique")

        expected_start = 0
        for section in self.sections:
            if section.start_bar != expected_start:
                raise ValueError("sections must be ordered, contiguous, and start at bar 0")
            expected_start = section.end_bar
        if expected_start != self.duration_bars:
            raise ValueError("sections must cover exactly duration_bars")

        known_sections = set(section_ids)
        for instrument in self.instrumentation:
            if instrument.entry_section_id not in known_sections:
                raise ValueError("instrument entry_section_id is not in sections")
            if instrument.exit_section_id not in known_sections:
                raise ValueError("instrument exit_section_id is not in sections")
            if section_ids.index(instrument.entry_section_id) > section_ids.index(
                instrument.exit_section_id
            ):
                raise ValueError("instrument exit section cannot precede entry section")
        return self


class PlanningResult(TypedDict):
    """Bounded, side-effect-free terminal output from composition planning."""

    phase: Literal["planning_complete", "planning_failed"]
    plan: NotRequired[dict[str, object]]
    provider_metadata: NotRequired[dict[str, str]]
    usage: NotRequired[dict[str, int | str | None]]
    counters: dict[str, int]
    fallback_reason: NotRequired[str]
    warnings: NotRequired[list[str]]
    error: NotRequired[dict[str, object]]


class ApprovalDecision(StrictSchema):
    decision: Literal["approve", "reject"]
    note: Annotated[str, Field(max_length=500)] = ""


class ErrorRecoveryDecision(StrictSchema):
    decision: Literal["fallback", "stop"]
    note: Annotated[str, Field(max_length=500)] = ""


class AgentErrorEnvelope(StrictSchema):
    """Compact, user-safe projection of the project ErrorEnvelope contract."""

    error_id: str = Field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    node: str
    category: Literal["input", "model_provider", "schema", "approval", "internal"]
    code: str
    safe_summary: str
    retryable: bool
    attempt: Annotated[int, Field(ge=0)] = 0
    provider: str | None = None
    model: str | None = None
    schema_version: str
    graph_topology_version: str
    suggested_route: Literal["retry", "repair", "fallback", "human", "terminal"]
