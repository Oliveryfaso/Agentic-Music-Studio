from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
    FeatureArtifact,
    FeatureProfile,
    MediaQualityProfile,
    RebuildInputArtifact,
    RebuildRecipe,
    RenderScope,
)
from pydantic import ValidationError


def _artifact(**overrides: object) -> AudioArtifact:
    values: dict[str, object] = {
        "artifact_id": uuid4(),
        "project_id": uuid4(),
        "source_job_id": uuid4(),
        "content_hash": "a" * 64,
        "byte_size": 1024,
        "storage_key": "sha256/aa/result.mp3",
        "media_role": "candidate_preview",
        "quality_profile": MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        "container": "mp3",
        "codec": "mp3",
        "sample_rate_hz": 48_000,
        "channels": 2,
        "duration_seconds": 60.0,
        "bitrate_kbps": 160,
        "encoder": "ffmpeg",
        "encoder_version": "7.1",
        "lifecycle_class": ArtifactLifecycle.PROTECTED,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return AudioArtifact.model_validate(values)


def test_candidate_preview_profile_is_exact_and_valid() -> None:
    artifact = _artifact()

    assert artifact.quality_profile is MediaQualityProfile.CANDIDATE_PREVIEW_V1
    assert artifact.bitrate_kbps == 160


def test_audition_profile_rejects_more_than_fifteen_seconds() -> None:
    with pytest.raises(ValidationError, match="cannot exceed 15 seconds"):
        _artifact(
            quality_profile=MediaQualityProfile.AUDITION_LITE_V1,
            bitrate_kbps=128,
            duration_seconds=15.001,
        )


def test_canonical_master_rejects_lossy_or_pcm16_output() -> None:
    with pytest.raises(ValidationError, match="requires WAV PCM24"):
        _artifact(
            quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            revision_id=uuid4(),
            arrangement_hash="d" * 64,
            render_scope=RenderScope.MASTER,
            container="wav",
            codec="pcm",
            bitrate_kbps=None,
            bit_depth=16,
        )


@pytest.mark.parametrize("storage_key", ["/tmp/result.mp3", "sha256/../result.mp3"])
def test_artifact_storage_key_cannot_escape_repository(storage_key: str) -> None:
    with pytest.raises(ValidationError, match="repository-relative"):
        _artifact(storage_key=storage_key)


def _recipe() -> RebuildRecipe:
    return RebuildRecipe(
        recipe_id=uuid4(),
        recipe_kind="time_stretch",
        input_artifacts=(RebuildInputArtifact(artifact_id=uuid4(), content_hash="c" * 64),),
        parameters={"source_bpm": 100.0, "target_bpm": 120.0, "preserve_pitch": True},
        engine="ffmpeg-atempo",
        engine_version="7.1",
        policy_version="time-stretch-quality-policy.v1",
        output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        expected_container="wav",
        expected_codec="pcm",
        expected_sample_rate_hz=48_000,
        expected_channels=2,
        expected_bit_depth=16,
        validation_rules=("duration-tolerance.v1", "pitch-preservation.v1"),
        idempotency_key="rehydrate-recipe-1",
    )


def test_rebuildable_artifact_requires_complete_hash_matching_recipe() -> None:
    recipe = _recipe()
    artifact = _artifact(
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        bitrate_kbps=None,
        bit_depth=16,
        lifecycle_class=ArtifactLifecycle.REBUILDABLE,
        rebuild_recipe=recipe,
        recipe_hash=recipe.content_hash,
    )

    assert artifact.rebuild_recipe == recipe
    with pytest.raises(ValidationError, match="complete RebuildRecipe"):
        _artifact(
            quality_profile=MediaQualityProfile.WORKING_PCM_V1,
            container="wav",
            codec="pcm",
            bitrate_kbps=None,
            bit_depth=16,
            lifecycle_class=ArtifactLifecycle.REBUILDABLE,
            recipe_hash="d" * 64,
        )


def test_evicted_artifact_requires_recipe_and_eviction_timestamp() -> None:
    recipe = _recipe()
    artifact = _artifact(
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        bitrate_kbps=None,
        bit_depth=16,
        lifecycle_class=ArtifactLifecycle.REBUILDABLE,
        availability=ArtifactAvailability.EVICTED,
        rebuild_recipe=recipe,
        recipe_hash=recipe.content_hash,
        evicted_at=datetime.now(UTC),
    )

    assert artifact.availability is ArtifactAvailability.EVICTED


def test_feature_artifact_requires_matching_rebuildable_recipe() -> None:
    source_id = uuid4()
    recipe = RebuildRecipe(
        recipe_id=uuid4(),
        recipe_kind="analysis",
        input_artifacts=(RebuildInputArtifact(artifact_id=source_id, content_hash="e" * 64),),
        parameters={"feature_profile": "waveform-peaks.v1", "timeout_seconds": 60.0},
        engine="motif-forge-audio-features",
        engine_version="v1",
        policy_version="audio-feature-policy.v1",
        output_feature_profile=FeatureProfile.WAVEFORM_PEAKS_V1,
        validation_rules=("json-schema.v1",),
        idempotency_key="feature-recipe-test",
    )
    artifact = FeatureArtifact(
        artifact_id=uuid4(),
        project_id=uuid4(),
        source_job_id=uuid4(),
        source_audio_artifact_id=source_id,
        source_audio_content_hash="e" * 64,
        content_hash="f" * 64,
        byte_size=512,
        storage_key="rebuildable/features/ff/result.json",
        feature_profile=FeatureProfile.WAVEFORM_PEAKS_V1,
        feature_schema_version="waveform-peaks.v1",
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=datetime.now(UTC),
    )

    assert artifact.lifecycle_class is ArtifactLifecycle.REBUILDABLE
    with pytest.raises(ValidationError, match="output profile"):
        FeatureArtifact.model_validate(
            artifact.model_dump() | {"feature_profile": FeatureProfile.IMPORT_ANALYSIS_V1}
        )
