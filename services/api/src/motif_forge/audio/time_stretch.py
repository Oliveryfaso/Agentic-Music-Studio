"""Offline pitch-preserving time-stretch using a controlled FFmpeg process."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Protocol
from uuid import UUID

TIME_STRETCH_RECIPE_VERSION = "time-stretch-recipe.v1"
TIME_STRETCH_POLICY_VERSION = "time-stretch-quality-policy.v1"


class TimeStretchError(RuntimeError):
    def __init__(self, code: str, safe_summary: str, *, retryable: bool = False) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TimeStretchRequest:
    job_id: UUID
    source_artifact_id: UUID
    source_bpm: float
    target_bpm: float
    preserve_pitch: bool = True
    timeout_seconds: float = 60.0

    def tempo_factor(self) -> float:
        if not self.preserve_pitch:
            raise TimeStretchError(
                "TIME_STRETCH_PITCH_POLICY_INVALID",
                "The first release only permits pitch-preserving time-stretch.",
            )
        if not 30 <= self.source_bpm <= 300 or not 30 <= self.target_bpm <= 300:
            raise TimeStretchError(
                "TIME_STRETCH_BPM_INVALID", "Source and target BPM must be between 30 and 300."
            )
        factor = self.target_bpm / self.source_bpm
        if not 0.5 <= factor <= 2.0:
            raise TimeStretchError(
                "TIME_STRETCH_RATIO_UNSUPPORTED",
                "The requested first-release stretch ratio is outside 0.5x to 2.0x.",
            )
        if not 1 <= self.timeout_seconds <= 600:
            raise TimeStretchError(
                "TIME_STRETCH_TIMEOUT_INVALID", "The Worker timeout is outside policy bounds."
            )
        return factor


@dataclass(frozen=True, slots=True)
class WavAnalysis:
    duration_seconds: float
    sample_rate: int
    channels: int
    rms: float
    peak: float
    maximum_jump: float
    fundamental_hz: float | None
    pitch_confidence: float


@dataclass(frozen=True, slots=True)
class TimeStretchQuality:
    expected_duration_seconds: float
    actual_duration_seconds: float
    duration_error_seconds: float
    pitch_deviation_cents: float | None
    pitch_check: str
    silence_detected: bool
    click_risk_detected: bool
    policy_version: str = TIME_STRETCH_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class DerivedArtifactRef:
    artifact_id: str
    sha256: str
    byte_size: int
    media_type: str
    storage_key: str


@dataclass(frozen=True, slots=True)
class TimeStretchResult:
    artifact: DerivedArtifactRef
    source_sha256: str
    tempo_factor: float
    engine: str
    engine_version: str
    recipe_hash: str
    quality: TimeStretchQuality


class TimeStretchWorkspace(Protocol):
    def resolve_source(self, artifact_id: UUID) -> Path: ...

    def allocate_pending(self, job_id: UUID) -> Path: ...

    def promote(self, pending_path: Path, checksum: str) -> DerivedArtifactRef: ...


class LocalTimeStretchWorkspace:
    """Path-safe local adapter for Worker-owned roots, not a browser API."""

    def __init__(
        self,
        root: Path,
        *,
        source_storage_keys: Mapping[UUID, str] | None = None,
    ) -> None:
        if root.is_symlink():
            raise ValueError("workspace root must be a specific non-symlink directory")
        self._root = root.resolve()
        if self._root == Path("/"):
            raise ValueError("workspace root must be a specific non-symlink directory")
        self._sources = self._root / "protected"
        self._pending = self._root / "tmp"
        self._derived = self._root / "derived"
        self._source_storage_keys = dict(source_storage_keys or {})
        for directory in (self._sources, self._pending, self._derived):
            directory.mkdir(parents=True, exist_ok=True)

    def source_slot(self, artifact_id: UUID) -> Path:
        """Return the controlled ingest slot; callers cannot choose its path."""

        return self._sources / f"{artifact_id}.wav"

    def resolve_source(self, artifact_id: UUID) -> Path:
        storage_key = self._source_storage_keys.get(artifact_id)
        if storage_key is None:
            path = self.source_slot(artifact_id)
        else:
            parts = storage_key.split("/")
            if storage_key.startswith("/") or ".." in parts or "" in parts:
                raise TimeStretchError(
                    "SOURCE_ARTIFACT_KEY_INVALID", "The source Artifact storage key is unsafe."
                )
            path = (self._root / storage_key).resolve()
            if self._root not in path.parents:
                raise TimeStretchError(
                    "SOURCE_ARTIFACT_KEY_INVALID", "The source Artifact storage key is unsafe."
                )
        if not path.is_file() or path.is_symlink():
            raise TimeStretchError(
                "SOURCE_ARTIFACT_UNAVAILABLE", "The normalized source Artifact is unavailable."
            )
        return path

    def allocate_pending(self, job_id: UUID) -> Path:
        job_directory = self._pending / str(job_id)
        if job_directory.is_symlink():
            raise TimeStretchError(
                "TIME_STRETCH_WORKSPACE_INVALID", "The Worker job directory is unsafe."
            )
        job_directory.mkdir(parents=True, exist_ok=True)
        return job_directory / "time-stretch.pending.wav"

    def promote(self, pending_path: Path, checksum: str) -> DerivedArtifactRef:
        expected_parent = self._pending.resolve()
        resolved_pending = pending_path.resolve()
        if expected_parent not in resolved_pending.parents or not resolved_pending.is_file():
            raise TimeStretchError(
                "TIME_STRETCH_OUTPUT_INVALID", "The Worker output is outside its controlled root."
            )
        destination_directory = self._derived / checksum[:2]
        destination_directory.mkdir(parents=True, exist_ok=True)
        destination = destination_directory / f"{checksum}.wav"
        if destination.exists():
            if _sha256(destination) != checksum:
                raise TimeStretchError(
                    "ARTIFACT_CHECKSUM_CONFLICT",
                    "An existing derived Artifact has an unexpected checksum.",
                )
            pending_path.unlink()
        else:
            os.replace(pending_path, destination)
        return DerivedArtifactRef(
            artifact_id=f"sha256:{checksum}",
            sha256=checksum,
            byte_size=destination.stat().st_size,
            media_type="audio/wav",
            storage_key=destination.relative_to(self._root).as_posix(),
        )


class PitchPreservingTimeStretch:
    def __init__(self, workspace: TimeStretchWorkspace, *, ffmpeg_binary: str = "ffmpeg") -> None:
        self._workspace = workspace
        self._ffmpeg = ffmpeg_binary

    def run(self, request: TimeStretchRequest) -> TimeStretchResult:
        factor = request.tempo_factor()
        source = self._workspace.resolve_source(request.source_artifact_id)
        source_checksum = _sha256(source)
        source_analysis = analyze_pcm16_wav(source)
        pending = self._workspace.allocate_pending(request.job_id)
        if pending.exists():
            raise TimeStretchError(
                "TIME_STRETCH_PENDING_CONFLICT",
                "A pending output already exists for this Job.",
            )
        engine_version = _ffmpeg_version(self._ffmpeg)
        recipe = {
            "schema_version": TIME_STRETCH_RECIPE_VERSION,
            "source_artifact_id": str(request.source_artifact_id),
            "source_sha256": source_checksum,
            "source_bpm": request.source_bpm,
            "target_bpm": request.target_bpm,
            "tempo_factor": factor,
            "preserve_pitch": True,
            "engine": "ffmpeg-atempo",
            "engine_version": engine_version,
            "output": {"codec": "pcm_s16le", "sample_rate": 48000, "channels": 2},
        }
        recipe_hash = hashlib.sha256(
            json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        command = [
            self._ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-filter:a",
            f"atempo={factor:.12g}",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(pending),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=request.timeout_seconds,
            )
            output_analysis = analyze_pcm16_wav(pending)
            quality = evaluate_time_stretch_quality(source_analysis, output_analysis, factor)
            if quality.silence_detected or quality.click_risk_detected:
                raise TimeStretchError(
                    "TIME_STRETCH_QUALITY_FAILED",
                    "The derived audio failed deterministic silence or transient checks.",
                )
            if quality.pitch_check == "failed":
                raise TimeStretchError(
                    "TIME_STRETCH_PITCH_DEVIATION",
                    "The derived audio did not preserve pitch within tolerance.",
                )
            if quality.duration_error_seconds > max(0.05, quality.expected_duration_seconds * 0.01):
                raise TimeStretchError(
                    "TIME_STRETCH_DURATION_DEVIATION",
                    "The derived audio duration is outside tolerance.",
                )
            checksum = _sha256(pending)
            artifact = self._workspace.promote(pending, checksum)
            return TimeStretchResult(
                artifact=artifact,
                source_sha256=source_checksum,
                tempo_factor=factor,
                engine="ffmpeg-atempo",
                engine_version=engine_version,
                recipe_hash=recipe_hash,
                quality=quality,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeStretchError(
                "TIME_STRETCH_TIMEOUT",
                "FFmpeg did not finish within the Worker deadline.",
                retryable=True,
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise TimeStretchError(
                "TIME_STRETCH_PROCESS_FAILED",
                "FFmpeg could not produce a valid derived WAV.",
                retryable=False,
            ) from exc
        finally:
            if pending.exists():
                pending.unlink()


def analyze_pcm16_wav(path: Path) -> WavAnalysis:
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            frame_count = audio.getnframes()
            if sample_width != 2 or channels not in {1, 2} or sample_rate not in {44100, 48000}:
                raise TimeStretchError(
                    "TIME_STRETCH_WAV_UNSUPPORTED",
                    "Time-stretch requires mono/stereo 16-bit PCM at 44.1 or 48 kHz.",
                )
            square_sum = 0.0
            peak = 0.0
            maximum_jump = 0.0
            previous: float | None = None
            sample_count = 0
            pitch_samples: list[float] = []
            frame_format = "<h" if channels == 1 else "<hh"
            while frames := audio.readframes(65_536):
                for frame in struct.iter_unpack(frame_format, frames):
                    value = frame[0] / 32768.0
                    square_sum += value * value
                    peak = max(peak, abs(value))
                    if previous is not None:
                        maximum_jump = max(maximum_jump, abs(value - previous))
                    previous = value
                    sample_count += 1
                    if len(pitch_samples) < sample_rate * 2:
                        pitch_samples.append(value)
    except (wave.Error, EOFError) as exc:
        raise TimeStretchError(
            "TIME_STRETCH_WAV_INVALID", "The normalized PCM WAV is invalid."
        ) from exc
    if sample_count == 0:
        raise TimeStretchError("TIME_STRETCH_WAV_EMPTY", "The source WAV contains no frames.")
    fundamental, confidence = _estimate_fundamental(pitch_samples, sample_rate)
    return WavAnalysis(
        duration_seconds=frame_count / sample_rate,
        sample_rate=sample_rate,
        channels=channels,
        rms=math.sqrt(square_sum / sample_count),
        peak=peak,
        maximum_jump=maximum_jump,
        fundamental_hz=fundamental,
        pitch_confidence=confidence,
    )


def evaluate_time_stretch_quality(
    source: WavAnalysis, output: WavAnalysis, tempo_factor: float
) -> TimeStretchQuality:
    expected_duration = source.duration_seconds / tempo_factor
    cents: float | None = None
    pitch_check = "inconclusive"
    if (
        source.fundamental_hz is not None
        and output.fundamental_hz is not None
        and source.pitch_confidence >= 0.7
        and output.pitch_confidence >= 0.7
    ):
        cents = 1200 * math.log2(output.fundamental_hz / source.fundamental_hz)
        pitch_check = "passed" if abs(cents) <= 25 else "failed"
    silence = output.rms < 0.0005 or output.peak < 0.002
    click_risk = output.maximum_jump > max(0.8, source.maximum_jump + 0.35)
    return TimeStretchQuality(
        expected_duration_seconds=expected_duration,
        actual_duration_seconds=output.duration_seconds,
        duration_error_seconds=abs(output.duration_seconds - expected_duration),
        pitch_deviation_cents=cents,
        pitch_check=pitch_check,
        silence_detected=silence,
        click_risk_detected=click_risk,
    )


def _estimate_fundamental(samples: list[float], sample_rate: int) -> tuple[float | None, float]:
    crossings: list[int] = []
    for index in range(1, len(samples)):
        if samples[index - 1] <= 0 < samples[index]:
            crossings.append(index)
    if len(crossings) < 12:
        return None, 0.0
    intervals = [right - left for left, right in pairwise(crossings)]
    mean = sum(intervals) / len(intervals)
    if mean <= 0:
        return None, 0.0
    variance = sum((interval - mean) ** 2 for interval in intervals) / len(intervals)
    coefficient = math.sqrt(variance) / mean
    confidence = max(0.0, min(1.0, 1.0 - coefficient * 8))
    return sample_rate / mean, confidence


def _ffmpeg_version(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise TimeStretchError(
            "FFMPEG_UNAVAILABLE", "The configured FFmpeg executable is unavailable."
        )
    try:
        result = subprocess.run(
            [resolved, "-version"], check=True, capture_output=True, text=True, timeout=5
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise TimeStretchError(
            "FFMPEG_VERSION_UNAVAILABLE", "FFmpeg version could not be verified."
        ) from exc
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    parts = first_line.split()
    if len(parts) < 3 or parts[0] != "ffmpeg" or parts[1] != "version":
        raise TimeStretchError(
            "FFMPEG_VERSION_INVALID", "FFmpeg returned an unexpected version string."
        )
    return parts[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
