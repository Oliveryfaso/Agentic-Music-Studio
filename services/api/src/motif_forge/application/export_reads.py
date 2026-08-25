"""Read-only S7 Export projections and safe Bundle file resolution."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from motif_forge.application.errors import ApplicationError
from motif_forge.application.generation import EXPORT_STEPS
from motif_forge.domain.media_jobs import ArtifactAvailability

ExportStatus = Literal["partial", "failed", "ready"]
ExportFileCategory = Literal["master", "stem", "delivery", "midi", "project", "manifest"]
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class ExportReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExportStepSummary(ExportReadModel):
    step: str = Field(min_length=1, max_length=80)
    job_id: UUID | None
    status: str = Field(min_length=1, max_length=32)
    artifact_id: UUID | None
    error_code: str | None = Field(default=None, max_length=100)


class ExportFileSummary(ExportReadModel):
    file_id: str = Field(min_length=1, max_length=200)
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    category: ExportFileCategory
    media_type: str = Field(min_length=1, max_length=100)
    byte_size: int = Field(ge=0)
    availability: ArtifactAvailability
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_url: str = Field(pattern=r"^/api/v1/")
    artifact_id: UUID | None = None


class ExportBundleSummary(ExportReadModel):
    bundle_id: UUID
    project_id: UUID
    revision_id: UUID
    availability: ArtifactAvailability
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    file_count: int = Field(ge=1)


class StoredExportBundle(ExportBundleSummary):
    storage_prefix: str = Field(min_length=1, max_length=500)


class RevisionExportProjection(ExportReadModel):
    project_id: UUID
    revision_id: UUID
    source_run_id: UUID | None
    status: ExportStatus
    bundle: ExportBundleSummary | None
    steps: tuple[ExportStepSummary, ...]
    files: tuple[ExportFileSummary, ...]
    error_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_ordered_steps(self) -> Self:
        if tuple(item.step for item in self.steps) != EXPORT_STEPS:
            raise ValueError("Export steps must use the canonical seven-step order")
        if self.status == "ready" and self.bundle is None:
            raise ValueError("ready Export requires a Bundle")
        if self.status == "failed" and self.error_code is None:
            raise ValueError("failed Export requires an error code")
        return self


class BundleFile(ExportReadModel):
    path: Path
    filename: str
    media_type: str


class ExportProjectionStore(Protocol):
    async def read_revision_export(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionExportProjection | None: ...

    async def read_bundle(self, bundle_id: UUID) -> StoredExportBundle | None: ...


class ReadRevisionExport:
    def __init__(self, store: ExportProjectionStore) -> None:
        self._store = store

    async def __call__(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionExportProjection:
        projection = await self._store.read_revision_export(
            project_id=project_id, revision_id=revision_id
        )
        if projection is None:
            raise ApplicationError(
                "REVISION_NOT_FOUND", "the revision does not belong to the project"
            )
        return projection


class ResolveBundleFile:
    def __init__(self, store: ExportProjectionStore, *, artifact_root: Path) -> None:
        self._store = store
        self._root = artifact_root.resolve()

    async def __call__(self, bundle_id: UUID, filename: str) -> BundleFile:
        if not SAFE_FILENAME.fullmatch(filename) or Path(filename).name != filename:
            raise ApplicationError("EXPORT_FILE_NAME_INVALID", "invalid Export filename")
        bundle = await self._store.read_bundle(bundle_id)
        if bundle is None:
            raise ApplicationError("EXPORT_BUNDLE_NOT_FOUND", "the Export Bundle does not exist")
        if bundle.availability is not ArtifactAvailability.AVAILABLE:
            raise ApplicationError("ARTIFACT_MISSING", "the Export Bundle is not available")
        directory = self._resolve_directory(bundle.storage_prefix)
        manifest_path = directory / "export-manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ApplicationError("EXPORT_MANIFEST_INVALID", "the Export manifest is unavailable")
        try:
            raw = manifest_path.read_bytes()
            if len(raw) > 1_000_000:
                raise ValueError("manifest too large")
            manifest = json.loads(raw)
            member = _manifest_member(manifest, bundle=bundle, filename=filename)
        except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError):
            raise ApplicationError(
                "EXPORT_MANIFEST_INVALID", "the Export manifest is invalid"
            ) from None
        target = directory / filename
        if target.is_symlink() or not target.is_file() or target.resolve().parent != directory:
            raise ApplicationError("ARTIFACT_MISSING", "the Export file is unavailable")
        content = target.read_bytes()
        if (
            len(content) != member["bytes"]
            or hashlib.sha256(content).hexdigest() != member["sha256"]
        ):
            raise ApplicationError(
                "EXPORT_FILE_INTEGRITY_INVALID", "the Export file failed integrity validation"
            )
        return BundleFile(path=target, filename=filename, media_type=_media_type(filename))

    def _resolve_directory(self, storage_prefix: str) -> Path:
        relative = Path(storage_prefix)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ApplicationError("EXPORT_ROOT_INVALID", "the Export root is invalid")
        current = self._root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ApplicationError("EXPORT_ROOT_INVALID", "the Export root is invalid")
        resolved = current.resolve()
        if not resolved.is_relative_to(self._root) or not resolved.is_dir():
            raise ApplicationError("EXPORT_ROOT_INVALID", "the Export root is invalid")
        return resolved


def _manifest_member(
    manifest: object, *, bundle: StoredExportBundle, filename: str
) -> dict[str, object]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "export-manifest.v1":
        raise ValueError("manifest schema invalid")
    if manifest.get("project_id") != str(bundle.project_id) or manifest.get("revision_id") != str(
        bundle.revision_id
    ):
        raise ValueError("manifest lineage invalid")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("manifest files invalid")
    matches = [
        item
        for item in files
        if isinstance(item, dict) and item.get("filename") == filename
    ]
    if len(matches) != 1:
        raise ValueError("manifest member invalid")
    member = matches[0]
    if (
        not isinstance(member.get("bytes"), int)
        or member["bytes"] < 0
        or not isinstance(member.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", member["sha256"]) is None
    ):
        raise ValueError("manifest member facts invalid")
    return member


def _media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return {
        ".json": "application/json",
        ".mid": "audio/midi",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
    }.get(suffix, "application/octet-stream")
