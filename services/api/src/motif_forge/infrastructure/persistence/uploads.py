"""PostgreSQL adapter for controlled upload sessions and source Artifacts."""

from __future__ import annotations

from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    ArtifactValidationStatus,
    AudioArtifact,
    MediaQualityProfile,
)
from motif_forge.domain.uploads import (
    DeclaredAudioFormat,
    RightsDeclaration,
    UploadPart,
    UploadSession,
    UploadStatus,
)
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    ProjectRow,
    UploadPartRow,
    UploadSessionRow,
)


class PostgresUploadUnitOfWork:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresUploadTransaction:
        return PostgresUploadTransaction(self._session_factory())


class PostgresUploadTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()

    async def project_exists(self, project_id: UUID) -> bool:
        return (
            await self._session.execute(select(ProjectRow.id).where(ProjectRow.id == project_id))
        ).scalar_one_or_none() is not None

    async def insert_upload_session(self, upload: UploadSession) -> None:
        await self._session.execute(insert(UploadSessionRow).values(**_upload_values(upload)))

    async def find_upload_session_by_key(
        self, *, project_id: UUID, idempotency_key: str
    ) -> UploadSession | None:
        row = (
            await self._session.execute(
                select(UploadSessionRow).where(
                    UploadSessionRow.project_id == project_id,
                    UploadSessionRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _upload_from_row(row)

    async def get_upload_session(
        self, upload_id: UUID, *, for_update: bool = False
    ) -> UploadSession | None:
        statement = select(UploadSessionRow).where(UploadSessionRow.id == upload_id)
        if for_update:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return None if row is None else _upload_from_row(row)

    async def update_upload_session(self, upload: UploadSession) -> None:
        values = _upload_values(upload)
        values.pop("id")
        await self._session.execute(
            update(UploadSessionRow).where(UploadSessionRow.id == upload.upload_id).values(**values)
        )

    async def get_upload_part(self, upload_id: UUID, part_number: int) -> UploadPart | None:
        row = (
            await self._session.execute(
                select(UploadPartRow).where(
                    UploadPartRow.upload_id == upload_id,
                    UploadPartRow.part_number == part_number,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return UploadPart(
            upload_id=row.upload_id,
            part_number=row.part_number,
            content_hash=row.content_hash,
            byte_size=row.byte_size,
            created_at=row.created_at,
        )

    async def insert_upload_part(self, part: UploadPart) -> None:
        await self._session.execute(
            insert(UploadPartRow).values(
                upload_id=part.upload_id,
                part_number=part.part_number,
                content_hash=part.content_hash,
                byte_size=part.byte_size,
                schema_version=part.schema_version,
                created_at=part.created_at,
            )
        )

    async def register_source_artifact(self, artifact: AudioArtifact) -> AudioArtifact:
        existing = (
            await self._session.execute(
                select(AudioArtifactRow).where(
                    AudioArtifactRow.project_id == artifact.project_id,
                    AudioArtifactRow.content_hash == artifact.content_hash,
                    AudioArtifactRow.quality_profile == artifact.quality_profile.value,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _artifact_from_row(existing)
        await self._session.execute(insert(AudioArtifactRow).values(**_artifact_values(artifact)))
        return artifact


def _upload_values(upload: UploadSession) -> dict[str, object]:
    return {
        "id": upload.upload_id,
        "project_id": upload.project_id,
        "original_filename": upload.original_filename,
        "declared_format": upload.declared_format.value,
        "rights_declaration": upload.rights_declaration.value,
        "expected_sha256": upload.expected_sha256,
        "idempotency_key": upload.idempotency_key,
        "request_hash": upload.request_hash,
        "declared_byte_size": upload.declared_byte_size,
        "part_size_bytes": upload.part_size_bytes,
        "received_bytes": upload.received_bytes,
        "next_part_number": upload.next_part_number,
        "status": upload.status.value,
        "quarantine_storage_key": upload.quarantine_storage_key,
        "detected_format": (
            upload.detected_format.value if upload.detected_format is not None else None
        ),
        "source_artifact_id": upload.source_artifact_id,
        "schema_version": upload.schema_version,
        "created_at": upload.created_at,
        "expires_at": upload.expires_at,
        "completed_at": upload.completed_at,
    }


def _upload_from_row(row: UploadSessionRow) -> UploadSession:
    return UploadSession(
        upload_id=row.id,
        project_id=row.project_id,
        original_filename=row.original_filename,
        declared_format=DeclaredAudioFormat(row.declared_format),
        rights_declaration=RightsDeclaration(row.rights_declaration),
        expected_sha256=row.expected_sha256,
        idempotency_key=row.idempotency_key,
        request_hash=row.request_hash,
        declared_byte_size=row.declared_byte_size,
        part_size_bytes=row.part_size_bytes,
        received_bytes=row.received_bytes,
        next_part_number=row.next_part_number,
        status=UploadStatus(row.status),
        quarantine_storage_key=row.quarantine_storage_key,
        detected_format=(
            DeclaredAudioFormat(row.detected_format) if row.detected_format is not None else None
        ),
        source_artifact_id=row.source_artifact_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        completed_at=row.completed_at,
    )


def _artifact_values(artifact: AudioArtifact) -> dict[str, object]:
    return {
        "id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "source_job_id": artifact.source_job_id,
        "source_upload_id": artifact.source_upload_id,
        "content_hash": artifact.content_hash,
        "byte_size": artifact.byte_size,
        "storage_key": artifact.storage_key,
        "media_role": artifact.media_role,
        "quality_profile": artifact.quality_profile.value,
        "container": artifact.container,
        "codec": artifact.codec,
        "sample_rate_hz": artifact.sample_rate_hz,
        "channels": artifact.channels,
        "duration_milliseconds": (
            round(artifact.duration_seconds * 1000)
            if artifact.duration_seconds is not None
            else None
        ),
        "bitrate_kbps": artifact.bitrate_kbps,
        "bit_depth": artifact.bit_depth,
        "encoder": artifact.encoder,
        "encoder_version": artifact.encoder_version,
        "lifecycle_class": artifact.lifecycle_class.value,
        "availability": artifact.availability.value,
        "validation_status": artifact.validation_status.value,
        "recipe_hash": artifact.recipe_hash,
        "rebuild_recipe": None,
        "protection_reasons": list(artifact.protection_reasons),
        "schema_version": artifact.schema_version,
        "created_at": artifact.created_at,
        "last_accessed_at": artifact.last_accessed_at,
        "expires_at": artifact.expires_at,
        "evicted_at": artifact.evicted_at,
        "rehydration_job_id": artifact.rehydration_job_id,
    }


def _artifact_from_row(row: AudioArtifactRow) -> AudioArtifact:
    return AudioArtifact(
        artifact_id=row.id,
        project_id=row.project_id,
        source_job_id=row.source_job_id,
        source_upload_id=row.source_upload_id,
        content_hash=row.content_hash,
        byte_size=row.byte_size,
        storage_key=row.storage_key,
        media_role=row.media_role,
        quality_profile=MediaQualityProfile(row.quality_profile),
        container=row.container,
        codec=row.codec,
        sample_rate_hz=row.sample_rate_hz,
        channels=row.channels,
        duration_seconds=(
            row.duration_milliseconds / 1000 if row.duration_milliseconds is not None else None
        ),
        bitrate_kbps=row.bitrate_kbps,
        bit_depth=row.bit_depth,
        encoder=row.encoder,
        encoder_version=row.encoder_version,
        lifecycle_class=ArtifactLifecycle(row.lifecycle_class),
        availability=ArtifactAvailability(row.availability),
        validation_status=ArtifactValidationStatus(row.validation_status),
        recipe_hash=row.recipe_hash,
        protection_reasons=tuple(row.protection_reasons),
        created_at=row.created_at,
        last_accessed_at=row.last_accessed_at,
        expires_at=row.expires_at,
        evicted_at=row.evicted_at,
        rehydration_job_id=row.rehydration_job_id,
    )
