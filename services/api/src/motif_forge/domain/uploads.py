"""Controlled audio-upload value objects before trusted Artifact ingestion."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.ir import DomainModel


class DeclaredAudioFormat(StrEnum):
    WAV = "wav"
    MP3 = "mp3"
    FLAC = "flac"


class RightsDeclaration(StrEnum):
    USER_OWNED = "user_owned"
    LICENSED = "licensed"
    PUBLIC_DOMAIN = "public_domain"
    CC0 = "cc0"
    CC_BY = "cc_by"


class UploadStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    EXPIRED = "expired"
    REJECTED = "rejected"


class UploadSession(DomainModel):
    """A sequential, bounded upload session; bytes remain quarantined."""

    schema_version: Literal["upload-session.v1"] = "upload-session.v1"
    upload_id: UUID
    project_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    declared_format: DeclaredAudioFormat
    rights_declaration: RightsDeclaration
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=160)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_byte_size: int = Field(gt=0)
    part_size_bytes: int = Field(gt=0)
    received_bytes: int = Field(default=0, ge=0)
    next_part_number: int = Field(default=1, ge=1)
    status: UploadStatus = UploadStatus.OPEN
    quarantine_storage_key: str | None = Field(default=None, min_length=1, max_length=500)
    detected_format: DeclaredAudioFormat | None = None
    source_artifact_id: UUID | None = None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if (
            "/" in self.original_filename
            or "\\" in self.original_filename
            or any(ord(character) < 32 for character in self.original_filename)
        ):
            raise ValueError("original_filename must be a plain filename")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.received_bytes > self.declared_byte_size:
            raise ValueError("received bytes cannot exceed declared byte size")
        complete_fields = (
            self.quarantine_storage_key,
            self.detected_format,
            self.source_artifact_id,
            self.completed_at,
        )
        if self.status is UploadStatus.COMPLETED:
            if any(value is None for value in complete_fields):
                raise ValueError("completed uploads require quarantine metadata")
            if self.received_bytes != self.declared_byte_size:
                raise ValueError("completed upload size must match the declaration")
        elif any(value is not None for value in complete_fields):
            raise ValueError("only completed uploads may expose quarantine metadata")
        return self


class UploadPartResult(DomainModel):
    upload_id: UUID
    accepted_part_number: int
    received_bytes: int
    next_part_number: int
    replayed: bool = False


class UploadPart(DomainModel):
    schema_version: Literal["upload-part.v1"] = "upload-part.v1"
    upload_id: UUID
    part_number: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    created_at: datetime
