"""Resolve validated audio bytes through Artifact IDs without exposing storage paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import MediaJobUnitOfWorkFactory
from motif_forge.domain.media_jobs import ArtifactAvailability, ArtifactValidationStatus


@dataclass(frozen=True, slots=True)
class AudioContent:
    path: Path
    media_type: str
    filename: str


class ResolveAudioContent:
    def __init__(self, uow_factory: MediaJobUnitOfWorkFactory, *, artifact_root: Path) -> None:
        self._uow_factory = uow_factory
        self._root = artifact_root.expanduser().resolve()

    async def __call__(self, artifact_id: UUID) -> AudioContent:
        async with self._uow_factory() as transaction:
            artifact = await transaction.get_audio_artifact(artifact_id)
        if artifact is None:
            raise ApplicationError("ARTIFACT_NOT_FOUND", "the Audio Artifact does not exist")
        if artifact.availability is ArtifactAvailability.EVICTED:
            raise ApplicationError("ARTIFACT_EVICTED", "the Audio Artifact must be rebuilt first")
        if artifact.availability is ArtifactAvailability.REHYDRATING:
            raise ApplicationError("ARTIFACT_REHYDRATING", "the Audio Artifact is rebuilding")
        if artifact.availability is ArtifactAvailability.MISSING:
            raise ApplicationError("ARTIFACT_MISSING", "the Audio Artifact is missing")
        if artifact.validation_status is not ArtifactValidationStatus.VALIDATED:
            raise ApplicationError(
                "ARTIFACT_NOT_PLAYABLE", "only validated Audio Artifacts may be streamed"
            )
        candidate = self._root / artifact.storage_key
        cursor = self._root
        contains_symlink = False
        for part in Path(artifact.storage_key).parts:
            cursor /= part
            if cursor.is_symlink():
                contains_symlink = True
                break
        path = candidate.resolve()
        if (
            not path.is_relative_to(self._root)
            or contains_symlink
            or not path.is_file()
            or path.stat().st_size != artifact.byte_size
        ):
            raise ApplicationError("ARTIFACT_MISSING", "the Audio Artifact bytes are missing")
        media_type = {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "flac": "audio/flac",
        }.get(artifact.container)
        if media_type is None:
            raise ApplicationError("ARTIFACT_NOT_PLAYABLE", "the audio container is not playable")
        return AudioContent(
            path=path,
            media_type=media_type,
            filename=f"motif-forge-{artifact.artifact_id}.{artifact.container}",
        )
