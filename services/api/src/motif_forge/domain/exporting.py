"""Strict complete Export Bundle value objects."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.ir import ArrangementIR, DomainModel
from motif_forge.domain.media_jobs import MediaQualityProfile


class AudioExportRef(DomainModel):
    artifact_id: UUID
    quality_profile: MediaQualityProfile
    storage_key: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    filename: str = Field(pattern=r"^[A-Za-z0-9._-]+$")


class ExportBundleRequest(DomainModel):
    schema_version: Literal["export-bundle-request.v1"] = "export-bundle-request.v1"
    project_id: UUID
    revision_id: UUID
    seed: int = Field(ge=0, le=2**31 - 1)
    arrangement: ArrangementIR
    arrangement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_exports: tuple[AudioExportRef, ...] = Field(min_length=6, max_length=6)
    engine_version: Literal["motif-forge-audio-engine.v1"]
    trace_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if self.arrangement.project_id != self.project_id:
            raise ValueError("arrangement must belong to project")
        if arrangement_content_hash(self.arrangement) != self.arrangement_hash:
            raise ValueError("arrangement_hash must match project JSON")
        profiles = [item.quality_profile for item in self.audio_exports]
        if profiles.count(MediaQualityProfile.CANONICAL_MASTER_V1) != 1:
            raise ValueError("bundle requires one canonical Master")
        if profiles.count(MediaQualityProfile.DELIVERY_MP3_V1) != 1:
            raise ValueError("bundle requires one delivery MP3")
        if profiles.count(MediaQualityProfile.CANONICAL_STEM_V1) != 4:
            raise ValueError("bundle requires four canonical Stems")
        if len({item.filename for item in self.audio_exports}) != 6:
            raise ValueError("bundle filenames must be unique")
        return self


class ExportBundleResult(DomainModel):
    schema_version: Literal["export-bundle-result.v1"] = "export-bundle-result.v1"
    storage_prefix: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_count: int = Field(ge=1)
    total_bytes: int = Field(gt=0)
    created_new: bool
