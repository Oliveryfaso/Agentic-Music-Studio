from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from motif_forge.application.exporting import write_export_bundle
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.exporting import AudioExportRef, ExportBundleRequest
from motif_forge.domain.media_jobs import MediaQualityProfile

PROJECT_ID = UUID("10000000-0000-4000-8000-000000000077")
REVISION_ID = UUID("20000000-0000-4000-8000-000000000077")


def _audio_ref(index: int, profile: MediaQualityProfile, filename: str) -> AudioExportRef:
    bytes_ = f"audio-{index}".encode()
    import hashlib

    return AudioExportRef(
        artifact_id=UUID(int=300 + index),
        quality_profile=profile,
        storage_key=f"protected/exports/{PROJECT_ID}/{REVISION_ID}/{filename}",
        sha256=hashlib.sha256(bytes_).hexdigest(),
        byte_size=len(bytes_),
        filename=filename,
    )


def test_export_bundle_writes_project_midi_and_all_manifests_with_checksums(
    tmp_path: Path,
) -> None:
    build = build_s1_composition(PROJECT_ID, seed=77)
    audio_refs = (
        _audio_ref(1, MediaQualityProfile.CANONICAL_MASTER_V1, "master.wav"),
        _audio_ref(2, MediaQualityProfile.DELIVERY_MP3_V1, "master.mp3"),
        *tuple(
            _audio_ref(10 + index, MediaQualityProfile.CANONICAL_STEM_V1, f"stem-{index}.wav")
            for index in range(4)
        ),
    )
    for index, ref in enumerate(audio_refs):
        path = tmp_path / ref.storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"audio-{1 if index == 0 else 2 if index == 1 else 8 + index}".encode())
    request = ExportBundleRequest(
        project_id=PROJECT_ID,
        revision_id=REVISION_ID,
        seed=77,
        arrangement=build.arrangement,
        arrangement_hash=build.content_hash,
        audio_exports=audio_refs,
        engine_version="motif-forge-audio-engine.v1",
        trace_refs=("trace:s1-smoke",),
    )

    result = write_export_bundle(artifact_root=tmp_path, request=request)

    bundle_root = tmp_path / result.storage_prefix
    manifest = json.loads((bundle_root / "export-manifest.json").read_text())
    assert result.schema_version == "export-bundle-result.v1"
    assert result.created_new is True
    assert len(manifest["files"]) == 12  # 6 audio + MIDI + Project + 4 supporting manifests
    assert (bundle_root / "project.json").is_file()
    assert (bundle_root / "composition.mid").read_bytes().startswith(b"MThd")
    assert (bundle_root / "credits.json").is_file()
    assert (bundle_root / "license.json").is_file()
    assert (bundle_root / "provenance.json").is_file()
    assert (bundle_root / "trace.json").is_file()
    assert not (bundle_root / "master.wav").exists()
    audio_entries = [item for item in manifest["files"] if "artifact_id" in item]
    assert len(audio_entries) == 6
    assert all(item["storage_key"].startswith("protected/exports/") for item in audio_entries)
    assert result.total_bytes == sum(path.stat().st_size for path in bundle_root.iterdir())

    (bundle_root / "project.json").write_bytes(b"tampered")
    try:
        write_export_bundle(artifact_root=tmp_path, request=request)
    except ValueError as exc:
        assert str(exc) == "EXPORT_IMMUTABLE_OUTPUT_CONFLICT"
    else:
        raise AssertionError("immutable bundle was overwritten")
    actual = hashlib.sha256((bundle_root / "project.json").read_bytes()).hexdigest()
    assert actual == hashlib.sha256(b"tampered").hexdigest()
