"""Explicit user-authorized scope for one finite semantic piano task."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.ir import DomainModel

PIANO_ACCOMPANIMENT_RUN_STATE_SCHEMA_VERSION = "piano-accompaniment-run.v1"


class PianoSemanticRequest(DomainModel):
    schema_version: Literal["piano-semantic-request.v1"] = "piano-semantic-request.v1"
    intent: str = Field(min_length=1, max_length=800)
    mode: Literal["append", "modify"]
    target_track_id: UUID | None = None
    start_bar: int = Field(default=1, ge=1, le=16)
    end_bar: int = Field(default=16, ge=1, le=16)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.mode == "append":
            if self.target_track_id is not None or (self.start_bar, self.end_bar) != (1, 16):
                raise ValueError("append requires the full sixteen bars and no existing target")
        elif self.target_track_id is None or not 1 <= self.end_bar - self.start_bar + 1 <= 4:
            raise ValueError("modify requires an existing target and one to four consecutive bars")
        return self
