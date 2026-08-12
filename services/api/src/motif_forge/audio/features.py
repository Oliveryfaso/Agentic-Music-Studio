"""Deterministic, compact JSON features derived from normalized PCM audio."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import Field

from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import FeatureProfile, ImportedAudioAnalysis

FEATURE_EXTRACTOR_VERSION = "audio-features.v1"
WAVEFORM_PEAKS_SCHEMA_VERSION = "waveform-peaks.v1"
_TARGET_BUCKETS = 4096


class WaveformPeak(DomainModel):
    minimum: int = Field(ge=-32768, le=32767)
    maximum: int = Field(ge=-32768, le=32767)


class WaveformPeaks(DomainModel):
    schema_version: str = WAVEFORM_PEAKS_SCHEMA_VERSION
    sample_rate_hz: int = Field(ge=8_000, le=192_000)
    source_channels: int = Field(ge=1, le=8)
    source_frames: int = Field(gt=0)
    bucket_size_frames: int = Field(gt=0)
    peaks: tuple[WaveformPeak, ...] = Field(min_length=1, max_length=_TARGET_BUCKETS)


@dataclass(frozen=True, slots=True)
class FeatureOutput:
    feature_profile: FeatureProfile
    feature_schema_version: str
    storage_key: str
    sha256: str
    byte_size: int


def write_import_features(
    path: Path,
    *,
    artifact_root: Path,
    project_id: UUID,
    source_content_hash: str,
    analysis: ImportedAudioAnalysis,
) -> tuple[FeatureOutput, FeatureOutput]:
    """Create idempotent content-addressed waveform and analysis JSON files."""

    peaks = extract_waveform_peaks(path)
    peaks_output = _write_feature(
        artifact_root=artifact_root,
        project_id=project_id,
        source_content_hash=source_content_hash,
        profile=FeatureProfile.WAVEFORM_PEAKS_V1,
        schema_version=WAVEFORM_PEAKS_SCHEMA_VERSION,
        payload=peaks.model_dump(mode="json"),
    )
    analysis_output = _write_feature(
        artifact_root=artifact_root,
        project_id=project_id,
        source_content_hash=source_content_hash,
        profile=FeatureProfile.IMPORT_ANALYSIS_V1,
        schema_version=analysis.schema_version,
        payload=analysis.model_dump(mode="json"),
    )
    return peaks_output, analysis_output


def write_feature_for_profile(
    path: Path,
    *,
    artifact_root: Path,
    project_id: UUID,
    source_content_hash: str,
    profile: FeatureProfile,
) -> FeatureOutput:
    """Rebuild one pinned feature profile without producing unrelated orphan files."""

    if profile is FeatureProfile.WAVEFORM_PEAKS_V1:
        peaks = extract_waveform_peaks(path)
        return _write_feature(
            artifact_root=artifact_root,
            project_id=project_id,
            source_content_hash=source_content_hash,
            profile=profile,
            schema_version=WAVEFORM_PEAKS_SCHEMA_VERSION,
            payload=peaks.model_dump(mode="json"),
        )
    analysis = _analyze_imported_audio(path)
    return _write_feature(
        artifact_root=artifact_root,
        project_id=project_id,
        source_content_hash=source_content_hash,
        profile=profile,
        schema_version=analysis.schema_version,
        payload=analysis.model_dump(mode="json"),
    )


def extract_waveform_peaks(path: Path) -> WaveformPeaks:
    """Collapse PCM16 mono/stereo frames into at most 4096 deterministic mono buckets."""

    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            if audio.getsampwidth() != 2 or channels not in {1, 2}:
                raise ValueError("waveform extraction requires mono/stereo PCM16")
            frame_count = audio.getnframes()
            if frame_count <= 0:
                raise ValueError("waveform extraction source is empty")
            bucket_size = max(1, (frame_count + _TARGET_BUCKETS - 1) // _TARGET_BUCKETS)
            peaks: list[WaveformPeak] = []
            while raw := audio.readframes(bucket_size):
                if channels == 1:
                    values = [item[0] for item in struct.iter_unpack("<h", raw)]
                else:
                    values = [
                        round((left + right) / 2)
                        for left, right in struct.iter_unpack("<hh", raw)
                    ]
                peaks.append(WaveformPeak(minimum=min(values), maximum=max(values)))
            return WaveformPeaks(
                sample_rate_hz=audio.getframerate(),
                source_channels=channels,
                source_frames=frame_count,
                bucket_size_frames=bucket_size,
                peaks=tuple(peaks),
            )
    except (EOFError, wave.Error) as exc:
        raise ValueError("waveform extraction source is not a valid PCM WAV") from exc


def _write_feature(
    *,
    artifact_root: Path,
    project_id: UUID,
    source_content_hash: str,
    profile: FeatureProfile,
    schema_version: str,
    payload: dict[str, object],
) -> FeatureOutput:
    envelope = {
        "feature_profile": profile.value,
        "feature_schema_version": schema_version,
        "source_content_hash": source_content_hash,
        "payload": payload,
    }
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    content_hash = hashlib.sha256(encoded).hexdigest()
    storage_key = (
        f"rebuildable/features/{project_id}/{profile.value}/{content_hash[:2]}/{content_hash}.json"
    )
    root = artifact_root.expanduser().resolve()
    destination = (root / storage_key).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("feature output escaped the Artifact Root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        stored_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
        if destination.is_symlink() or stored_hash != content_hash:
            raise ValueError("existing Feature Artifact failed checksum")
    else:
        pending = destination.with_suffix(".json.pending")
        pending.write_bytes(encoded)
        os.replace(pending, destination)
    return FeatureOutput(
        feature_profile=profile,
        feature_schema_version=schema_version,
        storage_key=storage_key,
        sha256=content_hash,
        byte_size=len(encoded),
    )


def _analyze_imported_audio(path: Path) -> ImportedAudioAnalysis:
    # Local import keeps the pure analysis module independent from this file's schemas.
    from motif_forge.audio.analysis import analyze_imported_audio

    return analyze_imported_audio(path)
