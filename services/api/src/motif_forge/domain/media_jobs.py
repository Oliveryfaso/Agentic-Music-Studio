"""Versioned media quality, asynchronous Job, and Artifact value objects."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.ir import DomainModel


class MediaQualityProfile(StrEnum):
    SOURCE_ORIGINAL_V1 = "source-original.v1"
    AUDITION_LITE_V1 = "audition-lite.v1"
    CANDIDATE_PREVIEW_V1 = "candidate-preview.v1"
    WORKING_PCM_V1 = "working-pcm.v1"
    CANONICAL_MASTER_V1 = "canonical-master.v1"
    CANONICAL_STEM_V1 = "canonical-stem.v1"
    DELIVERY_MP3_V1 = "delivery-mp3.v1"
    EXPORT_BUNDLE_V1 = "export-bundle.v1"


class FeatureProfile(StrEnum):
    WAVEFORM_PEAKS_V1 = "waveform-peaks.v1"
    IMPORT_ANALYSIS_V1 = "imported-audio-analysis.v1"


class ArtifactLifecycle(StrEnum):
    DURABLE = "durable"
    PROTECTED = "protected"
    REBUILDABLE = "rebuildable"
    EPHEMERAL = "ephemeral"


class ArtifactAvailability(StrEnum):
    AVAILABLE = "available"
    EVICTED = "evicted"
    MISSING = "missing"
    REHYDRATING = "rehydrating"


class ArtifactValidationStatus(StrEnum):
    QUARANTINED = "quarantined"
    VALIDATED = "validated"
    REJECTED = "rejected"


class RunStatus(StrEnum):
    WAITING_WORKER = "waiting_worker"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED = "cancelled"


class MediaJobType(StrEnum):
    INGEST = "ingest"
    RENDER_PREVIEW = "render_preview"
    TIME_STRETCH = "time_stretch"
    REHYDRATE = "rehydrate"
    REHYDRATE_FEATURE = "rehydrate_feature"
    TRANSCODE_AUDITION = "transcode_audition"
    RENDER_CANONICAL = "render_canonical"
    TRANSCODE_EXPORT = "transcode_export"
    EXPORT_BUNDLE = "export_bundle"


class RenderScope(StrEnum):
    MASTER = "master"
    STEM = "stem"


class CanonicalRenderJobPayload(DomainModel):
    schema_version: Literal["canonical-render-job.v1"] = "canonical-render-job.v1"
    project_id: UUID
    revision_id: UUID
    render_scope: RenderScope
    render_track_ids: tuple[UUID, ...]
    quality_profile: Literal[
        MediaQualityProfile.CANONICAL_MASTER_V1,
        MediaQualityProfile.CANONICAL_STEM_V1,
    ]
    audio_graph: dict[str, Any]
    audio_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    arrangement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_engine_version: Literal["motif-forge-audio-engine.v1"]
    seed: int = Field(ge=0, le=2**31 - 1)
    timeout_seconds: int = Field(ge=30, le=600)
    maximum_output_bytes: int = Field(ge=1_048_576, le=2_147_483_648)

    @model_validator(mode="after")
    def validate_render_contract(self) -> Self:
        encoded = json.dumps(
            self.audio_graph,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        if hashlib.sha256(encoded).hexdigest() != self.audio_graph_hash:
            raise ValueError("audio_graph_hash must match canonical audio_graph JSON")
        if self.audio_graph.get("engineVersion") != self.audio_engine_version:
            raise ValueError("audio_engine_version must match AudioGraphSpec")
        if self.audio_graph.get("sampleRate") != 48_000 or self.audio_graph.get("channels") != 2:
            raise ValueError("canonical render requires 48 kHz stereo AudioGraphSpec")
        if self.render_scope is RenderScope.MASTER:
            if self.render_track_ids:
                raise ValueError("master render cannot select individual tracks")
            if self.quality_profile is not MediaQualityProfile.CANONICAL_MASTER_V1:
                raise ValueError("master render requires canonical-master.v1")
        elif len(self.render_track_ids) != 1:
            raise ValueError("stem render requires exactly one track")
        elif self.quality_profile is not MediaQualityProfile.CANONICAL_STEM_V1:
            raise ValueError("stem render requires canonical-stem.v1")
        return self


class CandidatePreviewJobPayload(DomainModel):
    schema_version: Literal["candidate-preview-job.v1"] = "candidate-preview-job.v1"
    project_id: UUID
    candidate_snapshot_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_scope: Literal[RenderScope.MASTER] = RenderScope.MASTER
    render_track_ids: tuple[()] = ()
    quality_profile: Literal[MediaQualityProfile.CANDIDATE_PREVIEW_V1] = (
        MediaQualityProfile.CANDIDATE_PREVIEW_V1
    )
    audio_graph: dict[str, Any]
    audio_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_engine_version: Literal["motif-forge-audio-engine.v1"]
    seed: int = Field(ge=0, le=2**31 - 1)
    bitrate_kbps: Literal[160] = 160
    timeout_seconds: int = Field(ge=30, le=600)
    maximum_output_bytes: int = Field(ge=1_048_576, le=536_870_912)
    target_artifact_id: UUID | None = None
    expected_output_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_recipe_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_preview_render_contract(self) -> Self:
        rehydration_fields = (
            self.target_artifact_id,
            self.expected_output_content_hash,
            self.expected_recipe_hash,
        )
        if any(item is not None for item in rehydration_fields) and not all(
            item is not None for item in rehydration_fields
        ):
            raise ValueError("candidate preview rehydration identity must be complete")
        encoded = json.dumps(
            self.audio_graph,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        if hashlib.sha256(encoded).hexdigest() != self.audio_graph_hash:
            raise ValueError("audio_graph_hash must match canonical audio_graph JSON")
        if self.audio_graph.get("engineVersion") != self.audio_engine_version:
            raise ValueError("audio_engine_version must match AudioGraphSpec")
        if self.audio_graph.get("sampleRate") != 48_000 or self.audio_graph.get("channels") != 2:
            raise ValueError("candidate preview requires 48 kHz stereo AudioGraphSpec")
        return self


class ExportMp3JobPayload(DomainModel):
    schema_version: Literal["export-mp3-job.v1"] = "export-mp3-job.v1"
    project_id: UUID
    revision_id: UUID
    source_artifact_id: UUID
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bitrate_kbps: Literal[256] = 256
    timeout_seconds: int = Field(ge=30, le=300)


class BundleAudioInput(DomainModel):
    artifact_id: UUID
    quality_profile: Literal[
        MediaQualityProfile.CANONICAL_MASTER_V1,
        MediaQualityProfile.CANONICAL_STEM_V1,
        MediaQualityProfile.DELIVERY_MP3_V1,
    ]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(pattern=r"^[A-Za-z0-9._-]+$")


class ExportBundleJobPayload(DomainModel):
    schema_version: Literal["export-bundle-job.v1"] = "export-bundle-job.v1"
    project_id: UUID
    revision_id: UUID
    seed: int = Field(ge=0, le=2**31 - 1)
    arrangement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_inputs: tuple[BundleAudioInput, ...] = Field(min_length=6, max_length=6)
    engine_version: Literal["motif-forge-audio-engine.v1"]
    trace_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle_inputs(self) -> Self:
        profiles = [item.quality_profile for item in self.audio_inputs]
        if profiles.count(MediaQualityProfile.CANONICAL_MASTER_V1) != 1:
            raise ValueError("bundle requires one canonical Master")
        if profiles.count(MediaQualityProfile.DELIVERY_MP3_V1) != 1:
            raise ValueError("bundle requires one delivery MP3")
        if profiles.count(MediaQualityProfile.CANONICAL_STEM_V1) != 4:
            raise ValueError("bundle requires four canonical Stems")
        if len({item.artifact_id for item in self.audio_inputs}) != 6:
            raise ValueError("bundle inputs must reference six unique Artifacts")
        if len({item.filename for item in self.audio_inputs}) != 6:
            raise ValueError("bundle filenames must be unique")
        return self


class ImportedAudioAnalysis(DomainModel):
    schema_version: Literal["imported-audio-analysis.v1"] = "imported-audio-analysis.v1"
    analysis_version: Literal["import-analysis.v1"] = "import-analysis.v1"
    bpm: float | None = Field(default=None, ge=30.0, le=300.0, allow_inf_nan=False)
    bpm_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    key_tonic: Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] | None = (
        None
    )
    key_mode: Literal["major", "minor"] | None = None
    key_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    analyzed_seconds: float = Field(gt=0.0, le=120.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_optional_results(self) -> Self:
        if (self.key_tonic is None) != (self.key_mode is None):
            raise ValueError("key_tonic and key_mode must be present together")
        if self.bpm is None and self.bpm_confidence > 0.0:
            raise ValueError("unknown BPM must use zero confidence")
        if self.key_tonic is None and self.key_confidence > 0.0:
            raise ValueError("unknown key must use zero confidence")
        return self


class MediaRun(DomainModel):
    schema_version: Literal["media-run.v1"] = "media-run.v1"
    run_id: UUID
    project_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    run_type: str = Field(min_length=1, max_length=80)
    status: RunStatus = RunStatus.WAITING_WORKER
    waiting_for_job_id: UUID
    created_at: datetime
    updated_at: datetime


class MediaJob(DomainModel):
    schema_version: Literal["media-job.v1"] = "media-job.v1"
    job_id: UUID
    run_id: UUID
    project_id: UUID
    job_type: MediaJobType
    status: JobStatus = JobStatus.QUEUED
    idempotency_key: str = Field(min_length=8, max_length=160)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_payload: dict[str, Any]
    output_quality_profile: MediaQualityProfile | None = None
    output_feature_profile: FeatureProfile | None = None
    result_artifact_id: UUID | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    attempts: int = Field(default=0, ge=0, le=20)
    max_attempts: int = Field(default=3, ge=1, le=5)
    deadline_at: datetime
    heartbeat_at: datetime | None = None
    lease_owner: str | None = Field(default=None, min_length=1, max_length=160)
    lease_expires_at: datetime | None = None
    progress_percent: int = Field(default=0, ge=0, le=100)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_execution_contract(self) -> Self:
        if (self.output_quality_profile is None) == (self.output_feature_profile is None):
            raise ValueError("job requires exactly one output profile")
        if self.attempts > self.max_attempts:
            raise ValueError("attempts cannot exceed max_attempts")
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError("lease_owner and lease_expires_at must be set together")
        if self.deadline_at <= self.created_at:
            raise ValueError("deadline_at must be after created_at")
        return self


class TimeStretchJobPayload(DomainModel):
    schema_version: Literal["time-stretch-job.v1"] = "time-stretch-job.v1"
    source_artifact_id: UUID
    source_bpm: float = Field(ge=30.0, le=300.0, allow_inf_nan=False)
    target_bpm: float = Field(ge=30.0, le=300.0, allow_inf_nan=False)
    preserve_pitch: Literal[True] = True
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        factor = self.target_bpm / self.source_bpm
        if not 0.5 <= factor <= 2.0:
            raise ValueError("time-stretch ratio must be between 0.5x and 2.0x")
        return self


class RehydrateJobPayload(DomainModel):
    """Pinned Worker request compiled from one stored time-stretch RebuildRecipe."""

    schema_version: Literal["rehydrate-job.v1"] = "rehydrate-job.v1"
    target_artifact_id: UUID
    source_artifact_id: UUID
    source_bpm: float = Field(ge=30.0, le=300.0, allow_inf_nan=False)
    target_bpm: float = Field(ge=30.0, le=300.0, allow_inf_nan=False)
    preserve_pitch: Literal[True] = True
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0, allow_inf_nan=False)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_recipe_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        factor = self.target_bpm / self.source_bpm
        if not 0.5 <= factor <= 2.0:
            raise ValueError("time-stretch ratio must be between 0.5x and 2.0x")
        if self.target_artifact_id == self.source_artifact_id:
            raise ValueError("rehydration target and source Artifact must differ")
        return self


class FeatureRehydrateJobPayload(DomainModel):
    """Pinned request for rebuilding one deterministic JSON Feature Artifact."""

    schema_version: Literal["feature-rehydrate-job.v1"] = "feature-rehydrate-job.v1"
    target_artifact_id: UUID
    source_artifact_id: UUID
    feature_profile: FeatureProfile
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0, allow_inf_nan=False)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_recipe_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.target_artifact_id == self.source_artifact_id:
            raise ValueError("rehydration target and source Artifact must differ")
        return self


class IngestJobPayload(DomainModel):
    schema_version: Literal["ingest-job.v1"] = "ingest-job.v1"
    source_artifact_id: UUID
    target_sample_rate_hz: Literal[48_000] = 48_000
    target_channels: Literal[2] = 2
    target_bit_depth: Literal[16] = 16
    timeout_seconds: float = Field(default=120.0, ge=1.0, le=600.0, allow_inf_nan=False)


class RebuildInputArtifact(DomainModel):
    artifact_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RebuildRecipe(DomainModel):
    """Pinned, executable metadata for recreating one evictable Artifact."""

    schema_version: Literal["rebuild-recipe.v1"] = "rebuild-recipe.v1"
    recipe_id: UUID
    recipe_kind: Literal["time_stretch", "render", "analysis", "transcode"]
    input_artifacts: tuple[RebuildInputArtifact, ...] = ()
    parameters: dict[str, Any]
    engine: str = Field(min_length=1, max_length=120)
    engine_version: str = Field(min_length=1, max_length=80)
    policy_version: str = Field(min_length=1, max_length=80)
    output_quality_profile: MediaQualityProfile | None = None
    output_feature_profile: FeatureProfile | None = None
    expected_container: str | None = Field(default=None, min_length=1, max_length=24)
    expected_codec: str | None = Field(default=None, min_length=1, max_length=40)
    expected_sample_rate_hz: int | None = Field(default=None, ge=8_000, le=192_000)
    expected_channels: int | None = Field(default=None, ge=1, le=8)
    expected_bit_depth: int | None = Field(default=None, ge=8, le=64)
    validation_rules: tuple[str, ...] = Field(min_length=1)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_output_profile(self) -> Self:
        if self.recipe_kind != "render" and not self.input_artifacts:
            raise ValueError("non-render rebuild recipes require an input Artifact")
        if (self.output_quality_profile is None) == (self.output_feature_profile is None):
            raise ValueError("rebuild recipe requires exactly one output profile")
        if self.output_quality_profile is not None:
            if self.expected_container is None or self.expected_codec is None:
                raise ValueError("audio rebuild recipe requires media output fields")
        elif any(
            value is not None
            for value in (
                self.expected_container,
                self.expected_codec,
                self.expected_sample_rate_hz,
                self.expected_channels,
                self.expected_bit_depth,
            )
        ):
            raise ValueError("Feature rebuild recipe cannot declare audio media fields")
        return self

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class AudioArtifact(DomainModel):
    schema_version: Literal["audio-artifact.v2"] = "audio-artifact.v2"
    artifact_id: UUID
    project_id: UUID
    revision_id: UUID | None = None
    candidate_snapshot_id: UUID | None = None
    arrangement_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    render_scope: RenderScope | None = None
    render_track_ids: tuple[UUID, ...] = ()
    source_job_id: UUID | None = None
    source_upload_id: UUID | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    storage_key: str = Field(min_length=1, max_length=500)
    media_role: str = Field(min_length=1, max_length=80)
    quality_profile: MediaQualityProfile
    container: str = Field(min_length=1, max_length=24)
    codec: str = Field(min_length=1, max_length=40)
    sample_rate_hz: int | None = Field(default=None, ge=8_000, le=192_000)
    channels: int | None = Field(default=None, ge=1, le=8)
    duration_seconds: float | None = Field(default=None, gt=0.0, le=1800.0, allow_inf_nan=False)
    bitrate_kbps: int | None = Field(default=None, ge=32, le=1536)
    bit_depth: int | None = Field(default=None, ge=8, le=64)
    encoder: str = Field(min_length=1, max_length=120)
    encoder_version: str = Field(min_length=1, max_length=80)
    lifecycle_class: ArtifactLifecycle
    availability: ArtifactAvailability = ArtifactAvailability.AVAILABLE
    validation_status: ArtifactValidationStatus = ArtifactValidationStatus.VALIDATED
    recipe_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rebuild_recipe: RebuildRecipe | None = None
    protection_reasons: tuple[str, ...] = ()
    analysis: ImportedAudioAnalysis | None = None
    created_at: datetime
    last_accessed_at: datetime | None = None
    expires_at: datetime | None = None
    evicted_at: datetime | None = None
    rehydration_job_id: UUID | None = None

    @model_validator(mode="after")
    def validate_artifact_contract(self) -> Self:
        if (self.source_job_id is None) == (self.source_upload_id is None):
            raise ValueError("artifact requires exactly one source job or source upload")
        final_profiles = {
            MediaQualityProfile.CANONICAL_MASTER_V1,
            MediaQualityProfile.CANONICAL_STEM_V1,
            MediaQualityProfile.DELIVERY_MP3_V1,
        }
        if self.quality_profile in final_profiles and (
            self.revision_id is None
            or self.candidate_snapshot_id is not None
            or self.arrangement_hash is None
            or self.render_scope is None
        ):
            raise ValueError("canonical and delivery outputs require revision lineage")
        if self.quality_profile is MediaQualityProfile.CANDIDATE_PREVIEW_V1 and (
            self.candidate_snapshot_id is None
            or self.revision_id is not None
            or self.arrangement_hash is None
            or self.render_scope is not RenderScope.MASTER
            or self.render_track_ids
        ):
            raise ValueError("candidate preview requires candidate Snapshot lineage")
        if self.quality_profile is MediaQualityProfile.CANONICAL_STEM_V1:
            if self.render_scope is not RenderScope.STEM or len(self.render_track_ids) != 1:
                raise ValueError("canonical Stem requires one structured track scope")
        elif self.quality_profile in {
            MediaQualityProfile.CANONICAL_MASTER_V1,
            MediaQualityProfile.DELIVERY_MP3_V1,
        } and (self.render_scope is not RenderScope.MASTER or self.render_track_ids):
            raise ValueError("Master and MP3 outputs require whole-mix scope")
        elif self.quality_profile not in {
            *final_profiles,
            MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        } and (
            self.revision_id is not None
            or self.candidate_snapshot_id is not None
            or self.arrangement_hash is not None
            or self.render_scope is not None
            or self.render_track_ids
        ):
            raise ValueError("only rendered outputs carry arrangement lineage")
        key_parts = self.storage_key.split("/")
        if self.storage_key.startswith("/") or ".." in key_parts or "" in key_parts:
            raise ValueError("storage_key must be a safe repository-relative key")
        for field_name in ("created_at", "last_accessed_at", "expires_at", "evicted_at"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.lifecycle_class is ArtifactLifecycle.REBUILDABLE:
            if self.rebuild_recipe is None or self.recipe_hash is None:
                raise ValueError("rebuildable artifacts require a complete RebuildRecipe")
            if self.recipe_hash != self.rebuild_recipe.content_hash:
                raise ValueError("recipe_hash must match the complete RebuildRecipe")
        elif self.rebuild_recipe is not None:
            raise ValueError("only rebuildable artifacts may carry a RebuildRecipe")
        if (
            self.availability
            in {
                ArtifactAvailability.EVICTED,
                ArtifactAvailability.REHYDRATING,
            }
            and self.lifecycle_class is not ArtifactLifecycle.REBUILDABLE
        ):
            raise ValueError("only rebuildable artifacts may be evicted or rehydrating")
        if self.availability is ArtifactAvailability.EVICTED and self.evicted_at is None:
            raise ValueError("evicted artifacts require evicted_at")
        if self.availability is ArtifactAvailability.REHYDRATING:
            if self.rehydration_job_id is None:
                raise ValueError("rehydrating artifacts require rehydration_job_id")
        elif self.rehydration_job_id is not None:
            raise ValueError("rehydration_job_id is only valid while rehydrating")

        profile = self.quality_profile
        if profile is MediaQualityProfile.SOURCE_ORIGINAL_V1:
            if self.source_upload_id is None:
                raise ValueError("source-original.v1 requires a source upload")
            if self.container not in {"wav", "mp3", "flac"}:
                raise ValueError("source-original.v1 requires WAV, MP3, or FLAC")
            if self.validation_status is ArtifactValidationStatus.QUARANTINED:
                if any(
                    value is not None
                    for value in (
                        self.sample_rate_hz,
                        self.channels,
                        self.duration_seconds,
                        self.bitrate_kbps,
                        self.bit_depth,
                    )
                ):
                    raise ValueError("quarantined source metadata must not be guessed")
                return self
            self._require_decoded_metadata()
            return self
        if self.validation_status is not ArtifactValidationStatus.VALIDATED:
            raise ValueError("derived audio artifacts must be validated")
        self._require_decoded_metadata()
        if profile is MediaQualityProfile.AUDITION_LITE_V1:
            self._require_mp3(bitrate=128)
            assert self.duration_seconds is not None
            if self.duration_seconds > 15.0:
                raise ValueError("audition-lite.v1 cannot exceed 15 seconds")
        elif profile is MediaQualityProfile.CANDIDATE_PREVIEW_V1:
            self._require_mp3(bitrate=160)
            self._require_rate_and_channels()
        elif profile is MediaQualityProfile.WORKING_PCM_V1:
            self._require_pcm(bit_depth=16)
        elif profile in {
            MediaQualityProfile.CANONICAL_MASTER_V1,
            MediaQualityProfile.CANONICAL_STEM_V1,
        }:
            self._require_pcm(bit_depth=24)
        elif profile is MediaQualityProfile.DELIVERY_MP3_V1:
            self._require_mp3(bitrate=256)
            self._require_rate_and_channels()
        return self

    def _require_decoded_metadata(self) -> None:
        if self.sample_rate_hz is None or self.channels is None or self.duration_seconds is None:
            raise ValueError("validated audio requires decoded media metadata")

    def _require_mp3(self, *, bitrate: int) -> None:
        if self.container != "mp3" or self.codec != "mp3" or self.bitrate_kbps != bitrate:
            raise ValueError(f"{self.quality_profile} requires MP3 {bitrate} kbps")
        if self.bit_depth is not None:
            raise ValueError("lossy MP3 artifacts cannot declare bit_depth")

    def _require_pcm(self, *, bit_depth: int) -> None:
        self._require_rate_and_channels()
        if self.container != "wav" or self.codec != "pcm" or self.bit_depth != bit_depth:
            raise ValueError(f"{self.quality_profile} requires WAV PCM{bit_depth}")
        if self.bitrate_kbps is not None:
            raise ValueError("PCM artifacts cannot declare bitrate_kbps")

    def _require_rate_and_channels(self) -> None:
        if self.sample_rate_hz != 48_000 or self.channels != 2:
            raise ValueError(f"{self.quality_profile} requires 48 kHz stereo")


class FeatureArtifact(DomainModel):
    schema_version: Literal["feature-artifact.v1"] = "feature-artifact.v1"
    artifact_id: UUID
    project_id: UUID
    source_job_id: UUID
    source_audio_artifact_id: UUID
    source_audio_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    storage_key: str = Field(min_length=1, max_length=500)
    feature_profile: FeatureProfile
    feature_schema_version: str = Field(min_length=1, max_length=80)
    content_type: Literal["application/json"] = "application/json"
    lifecycle_class: ArtifactLifecycle = ArtifactLifecycle.REBUILDABLE
    availability: ArtifactAvailability = ArtifactAvailability.AVAILABLE
    recipe_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rebuild_recipe: RebuildRecipe
    protection_reasons: tuple[str, ...] = ()
    created_at: datetime
    last_accessed_at: datetime | None = None
    expires_at: datetime | None = None
    evicted_at: datetime | None = None
    rehydration_job_id: UUID | None = None

    @model_validator(mode="after")
    def validate_feature_contract(self) -> Self:
        key_parts = self.storage_key.split("/")
        if self.storage_key.startswith("/") or ".." in key_parts or "" in key_parts:
            raise ValueError("storage_key must be a safe repository-relative key")
        for field_name in ("created_at", "last_accessed_at", "expires_at", "evicted_at"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.recipe_hash != self.rebuild_recipe.content_hash:
            raise ValueError("recipe_hash must match the complete RebuildRecipe")
        if self.lifecycle_class is not ArtifactLifecycle.REBUILDABLE:
            raise ValueError("Feature Artifacts must remain rebuildable")
        if self.rebuild_recipe.output_feature_profile is not self.feature_profile:
            raise ValueError("recipe output profile must match the Feature Artifact")
        if self.availability is ArtifactAvailability.EVICTED and self.evicted_at is None:
            raise ValueError("evicted artifacts require evicted_at")
        if self.availability is ArtifactAvailability.REHYDRATING:
            if self.rehydration_job_id is None:
                raise ValueError("rehydrating artifacts require rehydration_job_id")
        elif self.rehydration_job_id is not None:
            raise ValueError("rehydration_job_id is only valid while rehydrating")
        return self


class ExportBundleArtifact(DomainModel):
    schema_version: Literal["export-bundle-artifact.v1"] = "export-bundle-artifact.v1"
    artifact_id: UUID
    project_id: UUID
    source_job_id: UUID
    revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    storage_prefix: str = Field(min_length=1, max_length=500)
    file_count: int = Field(ge=13, le=100)
    arrangement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    engine_version: Literal["motif-forge-audio-engine.v1"]
    seed: int = Field(ge=0, le=2**31 - 1)
    input_artifact_ids: tuple[UUID, ...] = Field(min_length=6, max_length=6)
    lifecycle_class: Literal[ArtifactLifecycle.PROTECTED] = ArtifactLifecycle.PROTECTED
    availability: Literal[ArtifactAvailability.AVAILABLE] = ArtifactAvailability.AVAILABLE
    created_new: bool = False
    created_at: datetime

    @model_validator(mode="after")
    def validate_bundle_artifact(self) -> Self:
        parts = self.storage_prefix.split("/")
        if self.storage_prefix.startswith("/") or ".." in parts or "" in parts:
            raise ValueError("storage_prefix must be a safe repository-relative key")
        if len(set(self.input_artifact_ids)) != 6:
            raise ValueError("bundle must preserve six unique input Artifact refs")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return self


class WorkerEvent(DomainModel):
    schema_version: Literal["worker-event.v1"] = "worker-event.v1"
    event_id: str = Field(min_length=1, max_length=200)
    job_id: UUID
    event_type: Literal["job.completed", "job.failed_retryable", "job.failed_terminal"]
    artifact: AudioArtifact | FeatureArtifact | ExportBundleArtifact | None = None
    feature_artifacts: tuple[FeatureArtifact, ...] = ()
    validated_source_artifact: AudioArtifact | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.event_type == "job.completed":
            if self.artifact is None or self.error_code is not None:
                raise ValueError("completed events require artifact and forbid error_code")
        elif (
            self.artifact is not None
            or self.feature_artifacts
            or self.validated_source_artifact is not None
            or self.error_code is None
        ):
            raise ValueError("failed events require error_code and forbid artifact")
        if self.validated_source_artifact is not None:
            source = self.validated_source_artifact
            if (
                source.quality_profile is not MediaQualityProfile.SOURCE_ORIGINAL_V1
                or source.validation_status is not ArtifactValidationStatus.VALIDATED
                or source.source_upload_id is None
            ):
                raise ValueError("source update must be a validated source-original Artifact")
        if self.feature_artifacts:
            if not isinstance(self.artifact, AudioArtifact):
                raise ValueError("secondary features require one primary Audio Artifact")
            for feature in self.feature_artifacts:
                if (
                    feature.project_id != self.artifact.project_id
                    or feature.source_job_id != self.job_id
                    or feature.source_audio_artifact_id != self.artifact.artifact_id
                    or feature.source_audio_content_hash != self.artifact.content_hash
                ):
                    raise ValueError("secondary Feature Artifact provenance does not match")
        return self


class WorkerResumePayload(DomainModel):
    schema_version: Literal["worker-resume.v1"] = "worker-resume.v1"
    run_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    run_type: str | None = Field(default=None, min_length=1, max_length=80)
    resume_event_id: str | None = Field(default=None, min_length=1, max_length=200)
    job_id: UUID
    status: Literal["succeeded", "failed_terminal"]
    artifact_id: UUID | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_resume(self) -> Self:
        if self.status == "succeeded":
            if self.artifact_id is None or self.error_code is not None:
                raise ValueError("successful resume requires artifact_id and forbids error_code")
        elif self.artifact_id is not None or self.error_code is None:
            raise ValueError("failed resume requires error_code and forbids artifact_id")
        return self
