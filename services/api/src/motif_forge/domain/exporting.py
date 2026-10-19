"""Strict complete Export Bundle value objects."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.export_plan import (
    CompleteExportCursorV2 as CompleteExportCursorV2,
)
from motif_forge.domain.export_plan import (
    ExportPlanValue,
    PianoExportPlanV3,
    verify_v1_export_source,
)
from motif_forge.domain.export_plan import (
    plan_export as plan_export,
)
from motif_forge.domain.export_plan import (
    verify_export_plan_revision as verify_export_plan_revision,
)
from motif_forge.domain.ir import ArrangementIR, ArrangementIRV2, ArrangementValue, DomainModel
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


class ExportBundleRequestV2(DomainModel):
    schema_version: Literal["export-bundle-request.v2"] = "export-bundle-request.v2"
    plan: ExportPlanValue
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    arrangement: ArrangementValue
    audio_exports: tuple[AudioExportRef, ...] = Field(min_length=1, max_length=14)
    trace_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if isinstance(self.arrangement, ArrangementIRV2):
            if (
                not isinstance(self.plan, PianoExportPlanV3)
                or self.plan.render_profile != self.arrangement.render_profile
            ):
                raise ValueError("EXPORT_SOURCE_PROFILE_UNSUPPORTED")
        else:
            verify_v1_export_source(self.arrangement)
        if self.plan_hash != self.plan.content_hash:
            raise ValueError("EXPORT_PLAN_HASH_MISMATCH")
        if (
            self.arrangement.project_id != self.plan.project_id
            or arrangement_content_hash(self.arrangement) != self.plan.arrangement_hash
            or tuple(sorted((t.track_id for t in self.arrangement.tracks), key=str))
            != self.plan.track_ids
        ):
            raise ValueError("EXPORT_PLAN_REVISION_MISMATCH")
        expected = dict(self.plan.audio_files)
        actual = {item.filename: item.quality_profile for item in self.audio_exports}
        if (
            len(actual) != len(self.audio_exports)
            or actual != expected
            or len({item.artifact_id for item in self.audio_exports}) != len(self.audio_exports)
        ):
            raise ValueError("EXPORT_AUDIO_SET_INVALID")
        return self

    @property
    def project_id(self) -> UUID:
        return self.plan.project_id

    @property
    def revision_id(self) -> UUID:
        return self.plan.revision_id

    @property
    def arrangement_hash(self) -> str:
        return self.plan.arrangement_hash

    @property
    def engine_version(self) -> str:
        return self.plan.engine_version

    @property
    def seed(self) -> int:
        return self.plan.seed
