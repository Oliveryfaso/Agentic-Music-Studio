"""Use cases for bounded upload sessions and quarantined source Artifacts."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import UploadError
from motif_forge.application.ports import UploadUnitOfWorkFactory
from motif_forge.audio.uploads import LocalUploadWorkspace, UploadWorkspaceError
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    ArtifactValidationStatus,
    AudioArtifact,
    MediaQualityProfile,
)
from motif_forge.domain.storage import StoragePressureDecision, StorageRoute
from motif_forge.domain.uploads import (
    DeclaredAudioFormat,
    RightsDeclaration,
    UploadPart,
    UploadPartResult,
    UploadSession,
    UploadStatus,
)


class CreateUploadSessionRequest(DomainModel):
    project_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    declared_format: DeclaredAudioFormat
    rights_declaration: RightsDeclaration
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=160)


class CompleteUploadResult(DomainModel):
    upload_id: UUID
    source_artifact_id: UUID
    content_hash: str
    byte_size: int
    detected_format: DeclaredAudioFormat
    validation_status: ArtifactValidationStatus
    replayed: bool = False


class UploadStorageGate(Protocol):
    async def __call__(
        self,
        *,
        operation_id: str,
        project_id: UUID,
        estimated_artifact_bytes: int,
        estimated_temp_bytes: int,
        requires_artifact_io: bool = True,
    ) -> StoragePressureDecision: ...


class CreateUploadSession:
    def __init__(
        self,
        uow_factory: UploadUnitOfWorkFactory,
        *,
        max_upload_bytes: int,
        part_size_bytes: int,
        ttl_hours: int,
        artifact_root: Path,
        min_free_bytes: int,
        storage_pressure_gate: UploadStorageGate | None = None,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._max_upload_bytes = max_upload_bytes
        self._part_size_bytes = part_size_bytes
        self._ttl_hours = ttl_hours
        self._artifact_root = artifact_root
        self._min_free_bytes = min_free_bytes
        self._storage_pressure_gate = storage_pressure_gate
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, request: CreateUploadSessionRequest) -> UploadSession:
        if request.byte_size > self._max_upload_bytes:
            raise UploadError("UPLOAD_TOO_LARGE", "the declared file exceeds the upload limit")
        now = self._clock()
        fingerprint = request_hash(
            {
                "schema": "upload-session-create.v1",
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        async with self._uow_factory() as transaction:
            existing = await transaction.find_upload_session_by_key(
                project_id=request.project_id, idempotency_key=request.idempotency_key
            )
            if existing is not None:
                if existing.request_hash != fingerprint:
                    raise UploadError(
                        "IDEMPOTENCY_KEY_REUSED",
                        "the idempotency key was used with a different upload request",
                    )
                return existing
            if not await transaction.project_exists(request.project_id):
                raise UploadError("PROJECT_NOT_FOUND", "the target project does not exist")
        if self._storage_pressure_gate is not None:
            decision = await self._storage_pressure_gate(
                operation_id=f"upload:{fingerprint}",
                project_id=request.project_id,
                estimated_artifact_bytes=request.byte_size,
                estimated_temp_bytes=request.byte_size,
            )
            if decision.route is not StorageRoute.PROCEED:
                raise UploadError(
                    decision.error_code or "STORAGE_QUOTA_EXCEEDED",
                    "the configured Artifact Root cannot safely accept this upload",
                    retryable=decision.route is StorageRoute.WAIT_FOR_STORAGE,
                )
        else:
            try:
                self._artifact_root.mkdir(parents=True, exist_ok=True)
                free_bytes = shutil.disk_usage(self._artifact_root).free
            except OSError as exc:
                raise UploadError(
                    "ARTIFACT_ROOT_UNAVAILABLE",
                    "the configured Artifact Root is unavailable",
                    retryable=True,
                ) from exc
            if free_bytes - request.byte_size < self._min_free_bytes:
                raise UploadError(
                    "STORAGE_QUOTA_EXCEEDED",
                    "the Artifact Root does not have enough safe free space",
                )
        upload = UploadSession(
            upload_id=self._id_factory(),
            project_id=request.project_id,
            original_filename=request.original_filename,
            declared_format=request.declared_format,
            rights_declaration=request.rights_declaration,
            expected_sha256=request.expected_sha256,
            idempotency_key=request.idempotency_key,
            request_hash=fingerprint,
            declared_byte_size=request.byte_size,
            part_size_bytes=self._part_size_bytes,
            created_at=now,
            expires_at=now + timedelta(hours=self._ttl_hours),
        )
        async with self._uow_factory() as transaction:
            existing = await transaction.find_upload_session_by_key(
                project_id=request.project_id, idempotency_key=request.idempotency_key
            )
            if existing is not None:
                if existing.request_hash != fingerprint:
                    raise UploadError(
                        "IDEMPOTENCY_KEY_REUSED",
                        "the idempotency key was used with a different upload request",
                    )
                return existing
            await transaction.insert_upload_session(upload)
        return upload


class PutUploadPart:
    def __init__(
        self,
        uow_factory: UploadUnitOfWorkFactory,
        workspace: LocalUploadWorkspace,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._workspace = workspace
        self._clock = clock

    async def __call__(
        self, *, upload_id: UUID, part_number: int, body: AsyncIterable[bytes]
    ) -> UploadPartResult:
        async with self._uow_factory() as transaction:
            upload = await transaction.get_upload_session(upload_id, for_update=True)
            if upload is None:
                raise UploadError("UPLOAD_NOT_FOUND", "the upload session does not exist")
            if upload.status is not UploadStatus.OPEN:
                raise UploadError("UPLOAD_STATE_CONFLICT", "the upload session is not open")
            if upload.expires_at <= self._clock():
                raise UploadError("UPLOAD_EXPIRED", "the upload session has expired")
            if part_number < upload.next_part_number:
                existing = await transaction.get_upload_part(upload_id, part_number)
                if existing is None:
                    raise UploadError(
                        "UPLOAD_STATE_CONFLICT", "persisted upload part metadata is missing"
                    )
                matches = await self._workspace.verify_replayed_part(
                    body=body,
                    expected_byte_size=existing.byte_size,
                    expected_sha256=existing.content_hash,
                )
                if not matches:
                    raise UploadError(
                        "UPLOAD_PART_CONFLICT",
                        "the retried part differs from the accepted part",
                    )
                return UploadPartResult(
                    upload_id=upload_id,
                    accepted_part_number=part_number,
                    received_bytes=upload.received_bytes,
                    next_part_number=upload.next_part_number,
                    replayed=True,
                )
            if part_number != upload.next_part_number:
                raise UploadError("UPLOAD_PART_OUT_OF_ORDER", "upload parts must be sequential")
            remaining = upload.declared_byte_size - upload.received_bytes
            max_bytes = min(upload.part_size_bytes, remaining)
            try:
                stored = await self._workspace.write_part(
                    upload_id=upload_id,
                    part_number=part_number,
                    body=body,
                    max_part_bytes=max_bytes,
                )
            except UploadWorkspaceError as exc:
                raise UploadError(exc.code, exc.message, retryable=exc.retryable) from exc
            updated = upload.model_copy(
                update={
                    "received_bytes": upload.received_bytes + stored.byte_size,
                    "next_part_number": upload.next_part_number + 1,
                }
            )
            await transaction.insert_upload_part(
                UploadPart(
                    upload_id=upload_id,
                    part_number=part_number,
                    content_hash=stored.sha256,
                    byte_size=stored.byte_size,
                    created_at=self._clock(),
                )
            )
            await transaction.update_upload_session(updated)
            return UploadPartResult(
                upload_id=upload_id,
                accepted_part_number=part_number,
                received_bytes=updated.received_bytes,
                next_part_number=updated.next_part_number,
            )


class CompleteUpload:
    def __init__(
        self,
        uow_factory: UploadUnitOfWorkFactory,
        workspace: LocalUploadWorkspace,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._workspace = workspace
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, upload_id: UUID) -> CompleteUploadResult:
        async with self._uow_factory() as transaction:
            upload = await transaction.get_upload_session(upload_id, for_update=True)
            if upload is None:
                raise UploadError("UPLOAD_NOT_FOUND", "the upload session does not exist")
            if upload.status is UploadStatus.COMPLETED:
                assert upload.source_artifact_id is not None
                assert upload.detected_format is not None
                return CompleteUploadResult(
                    upload_id=upload.upload_id,
                    source_artifact_id=upload.source_artifact_id,
                    content_hash=upload.expected_sha256,
                    byte_size=upload.declared_byte_size,
                    detected_format=upload.detected_format,
                    validation_status=ArtifactValidationStatus.QUARANTINED,
                    replayed=True,
                )
            if upload.status is not UploadStatus.OPEN:
                raise UploadError("UPLOAD_STATE_CONFLICT", "the upload session is not open")
            now = self._clock()
            if upload.expires_at <= now:
                raise UploadError("UPLOAD_EXPIRED", "the upload session has expired")
            if upload.received_bytes != upload.declared_byte_size:
                raise UploadError("UPLOAD_INCOMPLETE", "not all declared bytes were uploaded")
            try:
                completed = self._workspace.complete(
                    upload_id=upload.upload_id,
                    project_id=upload.project_id,
                    part_count=upload.next_part_number - 1,
                    declared_format=upload.declared_format,
                    expected_sha256=upload.expected_sha256,
                    expected_byte_size=upload.declared_byte_size,
                )
            except UploadWorkspaceError as exc:
                raise UploadError(exc.code, exc.message, retryable=exc.retryable) from exc
            candidate = AudioArtifact(
                artifact_id=self._id_factory(),
                project_id=upload.project_id,
                source_upload_id=upload.upload_id,
                content_hash=completed.sha256,
                byte_size=completed.byte_size,
                storage_key=completed.storage_key,
                media_role="uploaded_source_audio",
                quality_profile=MediaQualityProfile.SOURCE_ORIGINAL_V1,
                container=completed.detected_format.value,
                codec="unverified",
                encoder="user-upload",
                encoder_version="upload-session.v1",
                lifecycle_class=ArtifactLifecycle.DURABLE,
                validation_status=ArtifactValidationStatus.QUARANTINED,
                created_at=now,
            )
            artifact = await transaction.register_source_artifact(candidate)
            updated = upload.model_copy(
                update={
                    "status": UploadStatus.COMPLETED,
                    "quarantine_storage_key": completed.storage_key,
                    "detected_format": completed.detected_format,
                    "source_artifact_id": artifact.artifact_id,
                    "completed_at": now,
                }
            )
            await transaction.update_upload_session(updated)
        self._workspace.remove_parts(upload_id)
        return CompleteUploadResult(
            upload_id=upload_id,
            source_artifact_id=artifact.artifact_id,
            content_hash=artifact.content_hash,
            byte_size=artifact.byte_size,
            detected_format=completed.detected_format,
            validation_status=artifact.validation_status,
        )
