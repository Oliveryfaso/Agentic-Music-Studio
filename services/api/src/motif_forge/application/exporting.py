"""Atomic deterministic complete Export Bundle writer."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from typing import TypedDict

from motif_forge.audio.midi import arrangement_to_midi
from motif_forge.domain.canonical import canonical_json_bytes
from motif_forge.domain.exporting import ExportBundleRequest, ExportBundleResult


class _ManifestEntry(TypedDict, total=False):
    filename: str
    sha256: str
    bytes: int
    artifact_id: str
    quality_profile: str
    storage_key: str


def _entry_filename(item: _ManifestEntry) -> str:
    return item["filename"]


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def write_export_bundle(
    *,
    artifact_root: Path,
    request: ExportBundleRequest,
    cancel_event: threading.Event | None = None,
) -> ExportBundleResult:
    root = artifact_root.resolve()
    identity = hashlib.sha256(
        _json_bytes(
            {
                "schema_version": request.schema_version,
                "project_id": str(request.project_id),
                "revision_id": str(request.revision_id),
                "arrangement_hash": request.arrangement_hash,
                "audio": tuple(
                    (str(item.artifact_id), item.sha256, item.filename)
                    for item in request.audio_exports
                ),
                "engine_version": request.engine_version,
                "seed": request.seed,
            }
        )
    ).hexdigest()
    prefix = f"protected/exports/{request.project_id}/{request.revision_id}/bundles/{identity}"
    bundle = (root / prefix).resolve()
    if not bundle.is_relative_to(root):
        raise ValueError("EXPORT_ROOT_INVALID")
    created_new = not bundle.exists()
    bundle.mkdir(parents=True, exist_ok=True)
    if cancel_event is not None and cancel_event.is_set():
        if created_new:
            shutil.rmtree(bundle)
        raise ValueError("EXPORT_BUNDLE_CANCELLED")
    files: dict[str, bytes] = {
        "project.json": canonical_json_bytes(request.arrangement),
        "composition.mid": arrangement_to_midi(request.arrangement),
        "credits.json": _json_bytes({"schema_version": "credits.v1", "credits": []}),
        "license.json": _json_bytes(
            {"schema_version": "license-manifest.v1", "assets": [], "policy": "builtin-only"}
        ),
        "provenance.json": _json_bytes(
            {
                "schema_version": "provenance-manifest.v1",
                "project_id": str(request.project_id),
                "revision_id": str(request.revision_id),
                "arrangement_hash": request.arrangement_hash,
                "engine_version": request.engine_version,
                "seed": request.seed,
            }
        ),
        "trace.json": _json_bytes(
            {"schema_version": "trace-manifest.v1", "trace_refs": list(request.trace_refs)}
        ),
    }
    entries: list[_ManifestEntry] = []
    for audio in request.audio_exports:
        if cancel_event is not None and cancel_event.is_set():
            if created_new:
                shutil.rmtree(bundle)
            raise ValueError("EXPORT_BUNDLE_CANCELLED")
        source = (root / audio.storage_key).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError("EXPORT_AUDIO_UNAVAILABLE")
        bytes_ = source.read_bytes()
        if len(bytes_) != audio.byte_size or hashlib.sha256(bytes_).hexdigest() != audio.sha256:
            raise ValueError("EXPORT_AUDIO_CHECKSUM_MISMATCH")
        entries.append(
            {
                "filename": audio.filename,
                "sha256": audio.sha256,
                "bytes": audio.byte_size,
                "artifact_id": str(audio.artifact_id),
                "quality_profile": audio.quality_profile.value,
                "storage_key": audio.storage_key,
            }
        )
    for filename, bytes_ in files.items():
        if cancel_event is not None and cancel_event.is_set():
            if created_new:
                shutil.rmtree(bundle)
            raise ValueError("EXPORT_BUNDLE_CANCELLED")
        target = bundle / filename
        checksum = hashlib.sha256(bytes_).hexdigest()
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
                raise ValueError("EXPORT_IMMUTABLE_OUTPUT_CONFLICT")
            entries.append({"filename": filename, "sha256": checksum, "bytes": len(bytes_)})
            continue
        partial = bundle / f"{filename}.partial"
        partial.write_bytes(bytes_)
        os.replace(partial, target)
        entries.append(
            {
                "filename": filename,
                "sha256": checksum,
                "bytes": len(bytes_),
            }
        )
    entries.sort(key=_entry_filename)
    manifest = _json_bytes(
        {
            "schema_version": "export-manifest.v1",
            "project_id": str(request.project_id),
            "revision_id": str(request.revision_id),
            "files": entries,
        }
    )
    partial_manifest = bundle / "export-manifest.json.partial"
    manifest_target = bundle / "export-manifest.json"
    manifest_checksum = hashlib.sha256(manifest).hexdigest()
    if manifest_target.exists():
        if hashlib.sha256(manifest_target.read_bytes()).hexdigest() != manifest_checksum:
            raise ValueError("EXPORT_IMMUTABLE_OUTPUT_CONFLICT")
    else:
        partial_manifest.write_bytes(manifest)
        os.replace(partial_manifest, manifest_target)
    return ExportBundleResult(
        storage_prefix=prefix,
        manifest_sha256=manifest_checksum,
        file_count=len(entries) + 1,
        total_bytes=sum(len(item) for item in files.values()) + len(manifest),
        created_new=created_new,
    )
