"""Read compact Feature Artifact metadata and payloads for Studio consumers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import MediaJobUnitOfWorkFactory
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import ArtifactAvailability, FeatureArtifact


class FeatureArtifactView(DomainModel):
    artifact_id: UUID
    project_id: UUID
    source_audio_artifact_id: UUID
    feature_profile: str
    feature_schema_version: str
    availability: ArtifactAvailability
    content_hash: str
    byte_size: int
    payload: dict[str, Any] | None = None


class AudioFeatureSetView(DomainModel):
    source_audio_artifact_id: UUID
    features: tuple[FeatureArtifactView, ...]


class ListAudioFeatures:
    def __init__(self, uow_factory: MediaJobUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, source_audio_artifact_id: UUID) -> AudioFeatureSetView:
        async with self._uow_factory() as transaction:
            source = await transaction.get_audio_artifact(source_audio_artifact_id)
            features = await transaction.list_feature_artifacts_for_source(source_audio_artifact_id)
        if source is None:
            raise ApplicationError("ARTIFACT_NOT_FOUND", "the source Audio Artifact does not exist")
        return AudioFeatureSetView(
            source_audio_artifact_id=source_audio_artifact_id,
            features=tuple(_view(feature) for feature in features),
        )


class ReadFeatureArtifact:
    def __init__(self, uow_factory: MediaJobUnitOfWorkFactory, *, artifact_root: Path) -> None:
        self._uow_factory = uow_factory
        self._root = artifact_root.expanduser().resolve()

    async def __call__(self, artifact_id: UUID) -> FeatureArtifactView:
        async with self._uow_factory() as transaction:
            artifact = await transaction.get_feature_artifact(artifact_id)
        if artifact is None:
            raise ApplicationError("ARTIFACT_NOT_FOUND", "the Feature Artifact does not exist")
        if artifact.availability is ArtifactAvailability.EVICTED:
            return _view(artifact)
        if artifact.availability is ArtifactAvailability.REHYDRATING:
            return _view(artifact)
        if artifact.availability is ArtifactAvailability.MISSING:
            raise ApplicationError("ARTIFACT_MISSING", "the Feature Artifact is missing")
        path = (self._root / artifact.storage_key).resolve()
        if not path.is_relative_to(self._root) or path.is_symlink() or not path.is_file():
            raise ApplicationError("ARTIFACT_MISSING", "the Feature Artifact bytes are missing")
        encoded = path.read_bytes()
        if hashlib.sha256(encoded).hexdigest() != artifact.content_hash:
            raise ApplicationError("ARTIFACT_MISSING", "the Feature Artifact checksum failed")
        try:
            envelope = json.loads(encoded)
            payload = envelope["payload"]
            if not isinstance(payload, dict):
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ApplicationError(
                "ARTIFACT_MISSING", "the Feature Artifact payload is corrupt"
            ) from exc
        return _view(artifact, payload=payload)


def _view(
    artifact: FeatureArtifact, *, payload: dict[str, Any] | None = None
) -> FeatureArtifactView:
    return FeatureArtifactView(
        artifact_id=artifact.artifact_id,
        project_id=artifact.project_id,
        source_audio_artifact_id=artifact.source_audio_artifact_id,
        feature_profile=artifact.feature_profile.value,
        feature_schema_version=artifact.feature_schema_version,
        availability=artifact.availability,
        content_hash=artifact.content_hash,
        byte_size=artifact.byte_size,
        payload=payload,
    )
