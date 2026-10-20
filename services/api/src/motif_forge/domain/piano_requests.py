"""Explicit user-authorized scope for one finite semantic piano task."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from motif_forge.domain.ir import ArrangementIR, DomainModel
from motif_forge.domain.reviewed_scores import (
    REVIEWED_SCORES,
    ReviewedScore,
    ScoreId,
    reviewed_source,
)
from pydantic import Field, TypeAdapter, model_validator

PIANO_ACCOMPANIMENT_RUN_STATE_SCHEMA_VERSION = "piano-accompaniment-run.v1"


class PianoSemanticRequest(DomainModel):
    schema_version: Literal["piano-semantic-request.v1"] = "piano-semantic-request.v1"
    intent: str = Field(min_length=1, max_length=800)
    mode: Literal["append", "modify"]
    target_track_id: UUID | None = None
    start_bar: int = Field(default=1, ge=1, le=16)
    end_bar: int = Field(default=16, ge=1, le=16)

    @property
    def bar_ticks(self) -> int:
        return 1920

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.mode == "append":
            if self.target_track_id is not None or (self.start_bar, self.end_bar) != (1, 16):
                raise ValueError("append requires the full sixteen bars and no existing target")
        elif self.target_track_id is None or not 1 <= self.end_bar - self.start_bar + 1 <= 4:
            raise ValueError("modify requires an existing target and one to four consecutive bars")
        return self


class PianoSemanticRequestV2(DomainModel):
    schema_version: Literal["piano-semantic-request.v2"] = "piano-semantic-request.v2"
    source_score_id: ScoreId
    beats_per_bar: Literal[3, 4]
    intent: str = Field(min_length=1, max_length=800)
    mode: Literal["append", "modify"]
    target_track_id: UUID | None = None
    start_bar: int = Field(default=1, ge=1, le=16)
    end_bar: int = Field(ge=1, le=16)

    @property
    def bar_ticks(self) -> int:
        return self.beats_per_bar * 480

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        source = REVIEWED_SCORES[self.source_score_id]
        if source.score_id == "mutopia-528-melody.v1" or source.beats != self.beats_per_bar:
            raise ValueError("PIANO_SOURCE_MISMATCH")
        if not 1 <= self.start_bar <= self.end_bar <= source.measures:
            raise ValueError("ACCOMPANIMENT_SCOPE_INVALID")
        if self.mode == "append":
            if self.target_track_id is not None or (self.start_bar, self.end_bar) != (
                1,
                source.measures,
            ):
                raise ValueError("append requires every source bar and no existing target")
        elif self.target_track_id is None or self.end_bar - self.start_bar >= 4:
            raise ValueError("modify requires an existing target and one to four consecutive bars")
        return self


PianoSemanticInput = PianoSemanticRequest | PianoSemanticRequestV2


def read_piano_request(value: str) -> PianoSemanticInput:
    return TypeAdapter(PianoSemanticInput).validate_json(value, strict=True)


def require_semantic_source(base: ArrangementIR, request: PianoSemanticInput) -> ReviewedScore:
    source = reviewed_source(base)
    if isinstance(request, PianoSemanticRequestV2):
        if request.source_score_id != source.score_id or request.beats_per_bar != source.beats:
            raise ValueError("PIANO_SOURCE_MISMATCH")
    elif source.score_id != "mutopia-528-melody.v1":
        raise ValueError("PIANO_SOURCE_MISMATCH")
    return source
