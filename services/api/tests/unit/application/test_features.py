from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from motif_forge.application.features import ListAudioFeatures, ReadFeatureArtifact
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
    FeatureArtifact,
    FeatureProfile,
    MediaQualityProfile,
    RebuildInputArtifact,
    RebuildRecipe,
)


class FakeFeatures:
    def __init__(self, artifact: FeatureArtifact, source: AudioArtifact | None = None) -> None:
        self.artifact = artifact
        self.source = source

    def __call__(self) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def get_feature_artifact(self, artifact_id: UUID) -> FeatureArtifact | None:
        return self.artifact if artifact_id == self.artifact.artifact_id else None

    async def get_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None:
        return (
            self.source
            if self.source is not None and artifact_id == self.source.artifact_id
            else None
        )

    async def list_feature_artifacts_for_source(
        self, source_artifact_id: UUID
    ) -> tuple[FeatureArtifact, ...]:
        if self.artifact.source_audio_artifact_id == source_artifact_id:
            return (self.artifact,)
        return ()


def _artifact(root: Path) -> FeatureArtifact:
    source_id = uuid4()
    payload = {
        "feature_profile": "waveform-peaks.v1",
        "feature_schema_version": "waveform-peaks.v1",
        "source_content_hash": "a" * 64,
        "payload": {"peaks": [{"minimum": -1, "maximum": 1}]},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    import hashlib

    checksum = hashlib.sha256(encoded).hexdigest()
    key = f"rebuildable/features/{checksum}.json"
    path = root / key
    path.parent.mkdir(parents=True)
    path.write_bytes(encoded)
    recipe = RebuildRecipe(
        recipe_id=uuid4(),
        recipe_kind="analysis",
        input_artifacts=(RebuildInputArtifact(artifact_id=source_id, content_hash="a" * 64),),
        parameters={"feature_profile": "waveform-peaks.v1", "timeout_seconds": 60.0},
        engine="test",
        engine_version="v1",
        policy_version="audio-feature-policy.v1",
        output_feature_profile=FeatureProfile.WAVEFORM_PEAKS_V1,
        validation_rules=("json-schema.v1",),
        idempotency_key="feature-test-key",
    )
    return FeatureArtifact(
        artifact_id=uuid4(),
        project_id=uuid4(),
        source_job_id=uuid4(),
        source_audio_artifact_id=source_id,
        source_audio_content_hash="a" * 64,
        content_hash=checksum,
        byte_size=len(encoded),
        storage_key=key,
        feature_profile=FeatureProfile.WAVEFORM_PEAKS_V1,
        feature_schema_version="waveform-peaks.v1",
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_read_feature_returns_payload_only_when_available(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    loaded = await ReadFeatureArtifact(FakeFeatures(artifact), artifact_root=tmp_path)(
        artifact.artifact_id
    )  # type: ignore[arg-type]
    evicted = await ReadFeatureArtifact(
        FakeFeatures(
            artifact.model_copy(
                update={
                    "availability": ArtifactAvailability.EVICTED,
                    "evicted_at": datetime.now(UTC),
                }
            )
        ),
        artifact_root=tmp_path,
    )(artifact.artifact_id)  # type: ignore[arg-type]

    assert loaded.payload == {"peaks": [{"minimum": -1, "maximum": 1}]}
    assert evicted.payload is None


@pytest.mark.asyncio
async def test_list_audio_features_returns_metadata_without_loading_payload(tmp_path: Path) -> None:
    feature = _artifact(tmp_path)
    source = AudioArtifact(
        artifact_id=feature.source_audio_artifact_id,
        project_id=feature.project_id,
        source_job_id=feature.source_job_id,
        content_hash="a" * 64,
        byte_size=44,
        storage_key="protected/source.wav",
        media_role="normalized_import_audio",
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        sample_rate_hz=48_000,
        channels=2,
        bit_depth=16,
        encoder="ffmpeg",
        encoder_version="test",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        duration_seconds=1.0,
        created_at=datetime.now(UTC),
    )

    result = await ListAudioFeatures(FakeFeatures(feature, source))(source.artifact_id)  # type: ignore[arg-type]

    assert result.source_audio_artifact_id == source.artifact_id
    assert len(result.features) == 1
    assert result.features[0].feature_profile == "waveform-peaks.v1"
    assert result.features[0].payload is None
