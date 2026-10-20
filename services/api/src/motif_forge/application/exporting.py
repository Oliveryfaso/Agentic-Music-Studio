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
from motif_forge.domain.export_plan import PianoExportPlanV3
from motif_forge.domain.exporting import (
    ExportBundleRequest,
    ExportBundleRequestV2,
    ExportBundleResult,
)
from motif_forge.domain.ir import ArrangementIRV4, ArrangementIRV5


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
    request: ExportBundleRequest | ExportBundleRequestV2,
    cancel_event: threading.Event | None = None,
) -> ExportBundleResult:
    root = artifact_root.resolve()
    audio_exports = (
        tuple(sorted(request.audio_exports, key=lambda item: item.filename))
        if isinstance(request, ExportBundleRequestV2)
        else request.audio_exports
    )
    identity = hashlib.sha256(
        _json_bytes(
            {
                "schema_version": request.schema_version,
                "project_id": str(request.project_id),
                "revision_id": str(request.revision_id),
                "arrangement_hash": request.arrangement_hash,
                "audio": tuple(
                    (str(item.artifact_id), item.sha256, item.filename) for item in audio_exports
                ),
                "engine_version": request.engine_version,
                "seed": request.seed,
                **(
                    {"export_plan_hash": request.plan_hash, "trace_refs": request.trace_refs}
                    if isinstance(request, ExportBundleRequestV2)
                    else {}
                ),
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
    if isinstance(request.arrangement, ArrangementIRV4):
        provenance = json.loads(files["provenance.json"])
        provenance["piano_mix"] = request.arrangement.piano_mix.model_dump(mode="json")
        files["provenance.json"] = _json_bytes(provenance)
    if isinstance(request.arrangement, ArrangementIRV5):
        provenance = json.loads(files["provenance.json"])
        provenance["piano_eq"] = request.arrangement.piano_eq.model_dump(mode="json")
        provenance["eq_profile"] = request.arrangement.render_profile.eq_profile.model_dump(
            mode="json"
        )
        files["provenance.json"] = _json_bytes(provenance)
    if isinstance(request, ExportBundleRequestV2) and isinstance(request.plan, PianoExportPlanV3):
        profile = request.plan.render_profile
        source_url = (
            "https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-small-SFZ-20190703.7z"
        )
        files["credits.json"] = _json_bytes(
            {
                "schema_version": "credits.v1",
                "credits": [
                    {
                        "asset_id": profile.instrument_pack_id,
                        "pack_version": profile.instrument_pack_version,
                        "recorded_by": ["Gonzalo", "Roberto"],
                        "processed_by": "Roberto",
                        "source_url": source_url,
                        "manifest_sha256": profile.manifest_sha256,
                    }
                ],
            }
        )
        files["license.json"] = _json_bytes(
            {
                "schema_version": "license-manifest.v1",
                "policy": "builtin-and-reviewed-cc0.v1",
                "assets": [
                    {
                        "asset_id": profile.instrument_pack_id,
                        "pack_version": profile.instrument_pack_version,
                        "spdx": "CC0-1.0",
                        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                        "license_text_sha256": (
                            "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"
                        ),
                        "source_url": source_url,
                        "source_archive_sha256": (
                            "ffb547fceb91eeb93d78cf8d220d1d5f726dcac891afc15e517805ac48abb39d"
                        ),
                        "manifest_sha256": profile.manifest_sha256,
                    }
                ],
            }
        )
    score_refs = [p for p in request.arrangement.provenance if p.ref.startswith("score:")]
    if score_refs:
        from motif_forge.application.classical_import import reviewed_score
        from motif_forge.domain.reviewed_scores import reviewed_source

        try:
            score_identity = reviewed_source(request.arrangement)
        except ValueError as exc:
            raise ValueError("CLASSICAL_SOURCE_HASH_MISMATCH") from exc
        score_source, _ = reviewed_score(score_identity.score_id)
        score_credit = {
            "score_id": score_source["score_id"],
            "title": score_source["title"],
            "composer": score_source["composer"],
            "digital_editor": score_source["digital_editor"],
            "source_url": score_source["url"],
            "source_page": score_source["page"],
            "source_date": score_source["source_date"],
            "source_sha256": score_source["sha256"],
            "musicxml_sha256": score_source["musicxml_sha256"],
            "conversion": score_source["conversion"],
        }
        if "sources" in score_source:
            score_credit.update(
                {
                    key: score_source[key]
                    for key in (
                        "sources",
                        "sha256_scope",
                        "conversion_losses",
                        "integration_review",
                    )
                }
            )
        credits = json.loads(files["credits.json"])
        credits["credits"].append(score_credit)
        files["credits.json"] = _json_bytes(credits)
        licenses = json.loads(files["license.json"])
        licenses["policy"] = "builtin-and-reviewed-sources.v1"
        licenses["assets"].append(
            {
                **score_credit,
                "license": score_source["license"],
                "license_url": "https://www.mutopiaproject.org/legal.html",
            }
        )
        files["license.json"] = _json_bytes(licenses)
        provenance = json.loads(files["provenance.json"])
        provenance["score_source"] = score_credit
        files["provenance.json"] = _json_bytes(provenance)
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
            "schema_version": "export-manifest.v2"
            if isinstance(request, ExportBundleRequestV2)
            else "export-manifest.v1",
            **(
                {"export_plan_hash": request.plan_hash}
                if isinstance(request, ExportBundleRequestV2)
                else {}
            ),
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
