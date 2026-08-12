"""Filesystem boundary for bounded, quarantined user audio uploads."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from motif_forge.domain.uploads import DeclaredAudioFormat


class UploadWorkspaceError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class CompletedUpload:
    storage_key: str
    sha256: str
    byte_size: int
    detected_format: DeclaredAudioFormat


@dataclass(frozen=True, slots=True)
class StoredUploadPart:
    byte_size: int
    sha256: str


class LocalUploadWorkspace:
    """Own upload scratch and promotion without exposing host paths to callers."""

    def __init__(self, artifact_root: Path) -> None:
        self._root = artifact_root.expanduser().resolve()

    async def write_part(
        self,
        *,
        upload_id: UUID,
        part_number: int,
        body: AsyncIterable[bytes],
        max_part_bytes: int,
    ) -> StoredUploadPart:
        part_path = self._part_path(upload_id, part_number)
        self._prepare_parent(part_path)
        pending_path = part_path.with_suffix(".pending")
        written = 0
        digest = hashlib.sha256()
        try:
            with pending_path.open("wb") as output:
                for_aiter = body.__aiter__()
                while True:
                    try:
                        chunk = await for_aiter.__anext__()
                    except StopAsyncIteration:
                        break
                    written += len(chunk)
                    if written > max_part_bytes:
                        raise UploadWorkspaceError(
                            "UPLOAD_PART_TOO_LARGE",
                            "the upload part exceeds the configured part limit",
                        )
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if written == 0:
                raise UploadWorkspaceError("UPLOAD_PART_EMPTY", "upload parts cannot be empty")
            os.replace(pending_path, part_path)
        except OSError as exc:
            raise UploadWorkspaceError(
                "ARTIFACT_ROOT_UNAVAILABLE",
                "the external Artifact Root is not writable",
                retryable=True,
            ) from exc
        finally:
            if pending_path.exists():
                pending_path.unlink()
        return StoredUploadPart(byte_size=written, sha256=digest.hexdigest())

    async def verify_replayed_part(
        self,
        *,
        body: AsyncIterable[bytes],
        expected_byte_size: int,
        expected_sha256: str,
    ) -> bool:
        written = 0
        digest = hashlib.sha256()
        async for chunk in body:
            written += len(chunk)
            if written > expected_byte_size:
                return False
            digest.update(chunk)
        return written == expected_byte_size and digest.hexdigest() == expected_sha256

    def complete(
        self,
        *,
        upload_id: UUID,
        project_id: UUID,
        part_count: int,
        declared_format: DeclaredAudioFormat,
        expected_sha256: str,
        expected_byte_size: int,
    ) -> CompletedUpload:
        assembled = self._upload_directory(upload_id) / "assembled.pending"
        self._prepare_parent(assembled)
        digest = hashlib.sha256()
        byte_size = 0
        header = bytearray()
        try:
            with assembled.open("wb") as output:
                for part_number in range(1, part_count + 1):
                    part_path = self._part_path(upload_id, part_number)
                    if not part_path.is_file() or part_path.is_symlink():
                        raise UploadWorkspaceError(
                            "UPLOAD_PART_MISSING", "one or more upload parts are missing"
                        )
                    with part_path.open("rb") as source:
                        while chunk := source.read(1024 * 1024):
                            if len(header) < 16:
                                header.extend(chunk[: 16 - len(header)])
                            byte_size += len(chunk)
                            if byte_size > expected_byte_size:
                                raise UploadWorkspaceError(
                                    "UPLOAD_SIZE_MISMATCH",
                                    "uploaded bytes exceed the declared size",
                                )
                            digest.update(chunk)
                            output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            if byte_size != expected_byte_size:
                raise UploadWorkspaceError(
                    "UPLOAD_SIZE_MISMATCH", "uploaded bytes do not match the declared size"
                )
            checksum = digest.hexdigest()
            if checksum != expected_sha256:
                raise UploadWorkspaceError(
                    "UPLOAD_CHECKSUM_MISMATCH", "uploaded bytes do not match expected_sha256"
                )
            detected = detect_audio_format(bytes(header))
            if detected is not declared_format:
                raise UploadWorkspaceError(
                    "UPLOAD_FORMAT_MISMATCH",
                    "magic bytes do not match the declared audio format",
                )

            storage_key = (
                f"quarantine/source-original/{project_id}/{checksum[:2]}/"
                f"{checksum}.{detected.value}"
            )
            destination = self._resolve_storage_key(storage_key)
            self._prepare_parent(destination)
            if destination.exists():
                if destination.is_symlink() or _sha256_file(destination) != checksum:
                    raise UploadWorkspaceError(
                        "ARTIFACT_HASH_COLLISION", "an existing stored object failed checksum"
                    )
                assembled.unlink()
            else:
                os.replace(assembled, destination)
            return CompletedUpload(storage_key, checksum, byte_size, detected)
        except OSError as exc:
            raise UploadWorkspaceError(
                "ARTIFACT_ROOT_UNAVAILABLE",
                "the external Artifact Root is not writable",
                retryable=True,
            ) from exc
        finally:
            if assembled.exists():
                assembled.unlink()

    def remove_parts(self, upload_id: UUID) -> None:
        directory = self._upload_directory(upload_id)
        try:
            if directory.exists() and not directory.is_symlink():
                shutil.rmtree(directory)
        except OSError:
            # Completion is already durable; a later retention sweep can remove scratch.
            return

    def _upload_directory(self, upload_id: UUID) -> Path:
        return self._resolve_storage_key(f"tmp/uploads/{upload_id}")

    def _part_path(self, upload_id: UUID, part_number: int) -> Path:
        if part_number < 1:
            raise UploadWorkspaceError("UPLOAD_PART_INVALID", "part numbers start at one")
        return self._upload_directory(upload_id) / f"{part_number:08d}.part"

    def _resolve_storage_key(self, storage_key: str) -> Path:
        if storage_key.startswith("/") or ".." in storage_key.split("/"):
            raise UploadWorkspaceError("UPLOAD_STORAGE_KEY_INVALID", "unsafe storage key")
        resolved = (self._root / storage_key).resolve()
        if not resolved.is_relative_to(self._root):
            raise UploadWorkspaceError("UPLOAD_STORAGE_KEY_INVALID", "unsafe storage key")
        return resolved

    def _prepare_parent(self, path: Path) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink():
            raise UploadWorkspaceError("ARTIFACT_ROOT_UNAVAILABLE", "Artifact Root is a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.parent
        while current != self._root:
            if current.is_symlink():
                raise UploadWorkspaceError("UPLOAD_STORAGE_KEY_INVALID", "symlinks are forbidden")
            current = current.parent


def detect_audio_format(header: bytes) -> DeclaredAudioFormat:
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return DeclaredAudioFormat.WAV
    if header.startswith(b"fLaC"):
        return DeclaredAudioFormat.FLAC
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    ):
        return DeclaredAudioFormat.MP3
    raise UploadWorkspaceError(
        "UPLOAD_MEDIA_TYPE_UNSUPPORTED", "only WAV, MP3, and FLAC audio are accepted"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
