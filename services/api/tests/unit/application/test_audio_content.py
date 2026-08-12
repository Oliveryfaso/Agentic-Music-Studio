from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from motif_forge.application.audio_content import ResolveAudioContent
from motif_forge.application.errors import ApplicationError
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    ArtifactValidationStatus,
    AudioArtifact,
    MediaQualityProfile,
)


class FakeAudioTransaction:
    def __init__(self, artifact: AudioArtifact | None) -> None:
        self.artifact = artifact

    async def __aenter__(self) -> FakeAudioTransaction:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None:
        return self.artifact if self.artifact and self.artifact.artifact_id == artifact_id else None


def artifact(
    root: Path, *, availability: ArtifactAvailability = ArtifactAvailability.AVAILABLE
) -> AudioArtifact:
    artifact_id = uuid4()
    path = root / "protected" / f"{artifact_id}.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFF-safe-audio")
    return AudioArtifact(
        artifact_id=artifact_id,
        project_id=uuid4(),
        source_job_id=uuid4(),
        content_hash="a" * 64,
        byte_size=path.stat().st_size,
        storage_key=f"protected/{artifact_id}.wav",
        media_role="normalized_import_audio",
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=1.0,
        bit_depth=16,
        encoder="fixture",
        encoder_version="1",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        availability=availability,
        validation_status=ArtifactValidationStatus.VALIDATED,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_audio_content_resolves_validated_artifact_under_root(tmp_path: Path) -> None:
    value = artifact(tmp_path)
    resolved = await ResolveAudioContent(
        lambda: FakeAudioTransaction(value), artifact_root=tmp_path
    )(value.artifact_id)
    assert resolved.media_type == "audio/wav"
    assert resolved.path.is_file()


@pytest.mark.asyncio
async def test_audio_content_rejects_unavailable_artifact(tmp_path: Path) -> None:
    value = artifact(tmp_path, availability=ArtifactAvailability.MISSING)
    with pytest.raises(ApplicationError, match="ARTIFACT_MISSING"):
        await ResolveAudioContent(lambda: FakeAudioTransaction(value), artifact_root=tmp_path)(
            value.artifact_id
        )


@pytest.mark.asyncio
async def test_audio_content_rejects_symlinked_storage_path(tmp_path: Path) -> None:
    value = artifact(tmp_path)
    real_path = tmp_path / value.storage_key
    target = tmp_path / "target.wav"
    target.write_bytes(real_path.read_bytes())
    real_path.unlink()
    real_path.symlink_to(target)
    with pytest.raises(ApplicationError, match="ARTIFACT_MISSING"):
        await ResolveAudioContent(lambda: FakeAudioTransaction(value), artifact_root=tmp_path)(
            value.artifact_id
        )
