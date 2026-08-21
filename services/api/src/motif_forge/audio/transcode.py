"""Bounded FFmpeg delivery transcode from canonical PCM24 Master to MP3."""

from __future__ import annotations

import hashlib
import re
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from motif_forge.audio.atomic_promote import AtomicPromoteError, promote_verified_file

_SILENT_MAX_VOLUME_DB = -80.0
# -80 dBFS is below intentional low-level musical content for the delivery profile
# while remaining above FFmpeg's finite digital-floor readings (for example -91 dBFS).
_MAX_VOLUME_PATTERN = re.compile(r"max_volume:\s*(?P<value>-inf|-?\d+(?:\.\d+)?)\s*dB")


class ExportTranscodeError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Mp3TranscodeResult:
    storage_key: str
    sha256: str
    byte_size: int
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    bitrate_kbps: int
    created_new: bool


def _safe(root: Path, key: str) -> Path:
    if key.startswith("/") or ".." in key.split("/"):
        raise ExportTranscodeError("TRANSCODE_STORAGE_KEY_INVALID")
    resolved_root = root.resolve()
    path = (resolved_root / key).resolve()
    if not path.is_relative_to(resolved_root):
        raise ExportTranscodeError("TRANSCODE_STORAGE_KEY_INVALID")
    return path


def transcode_master_to_mp3(
    *,
    artifact_root: Path,
    temp_root: Path,
    job_id: UUID,
    project_id: UUID,
    revision_id: UUID | None = None,
    candidate_snapshot_id: UUID | None = None,
    bitrate_kbps: int = 256,
    source_storage_key: str,
    expected_duration_seconds: float,
    timeout_seconds: int,
    cancel_event: threading.Event | None = None,
) -> Mp3TranscodeResult:
    if (revision_id is None) == (candidate_snapshot_id is None):
        raise ExportTranscodeError("TRANSCODE_LINEAGE_INVALID")
    if bitrate_kbps not in {160, 256}:
        raise ExportTranscodeError("TRANSCODE_BITRATE_INVALID")
    root = artifact_root.resolve()
    resolved_temp_root = temp_root.resolve()
    source = _safe(root, source_storage_key)
    if not source.is_file():
        raise ExportTranscodeError("SOURCE_ARTIFACT_UNAVAILABLE")
    if not resolved_temp_root.is_dir():
        raise ExportTranscodeError("TEMP_ROOT_UNAVAILABLE", retryable=True)
    temp_key = f"jobs/{job_id}/master.mp3.partial"
    temporary = _safe(resolved_temp_root, temp_key)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = _run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-ar",
                "48000",
                "-ac",
                "2",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                f"{bitrate_kbps}k",
                "-map_metadata",
                "-1",
                "-f",
                "mp3",
                "-y",
                str(temporary),
            ],
            timeout=timeout_seconds,
            cancel_event=cancel_event,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExportTranscodeError("TRANSCODE_TIMEOUT", retryable=True) from exc
    if completed.returncode != 0 or not temporary.is_file():
        raise ExportTranscodeError("TRANSCODE_FAILED")
    try:
        probe = _run_process(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels,bit_rate:format=duration,bit_rate",
                "-of",
                "json",
                str(temporary),
            ],
            text=True,
            timeout=min(timeout_seconds, 30),
            cancel_event=cancel_event,
        )
        if probe.returncode != 0:
            raise ExportTranscodeError("TRANSCODE_MEDIA_INVALID")
        try:
            import json

            metadata = json.loads(probe.stdout)
            stream = metadata["streams"][0]
            duration = float(metadata["format"]["duration"])
            sample_rate = int(stream["sample_rate"])
            channels = int(stream["channels"])
            bitrate = int(stream.get("bit_rate") or metadata["format"]["bit_rate"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExportTranscodeError("TRANSCODE_MEDIA_INVALID") from exc
        minimum_bitrate = (bitrate_kbps - 24) * 1000
        if sample_rate != 48_000 or channels != 2 or duration <= 0 or bitrate < minimum_bitrate:
            raise ExportTranscodeError("TRANSCODE_MEDIA_PROFILE_INVALID")
        if abs(duration - expected_duration_seconds) > 0.05:
            raise ExportTranscodeError("TRANSCODE_DURATION_MISMATCH")
        loudness = _run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                str(temporary),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            timeout=min(timeout_seconds, 30),
            cancel_event=cancel_event,
        )
        stderr = (
            loudness.stderr.decode(errors="replace")
            if isinstance(loudness.stderr, bytes)
            else loudness.stderr
        )
        maximum = _MAX_VOLUME_PATTERN.search(stderr)
        if (
            loudness.returncode != 0
            or maximum is None
            or maximum.group("value") == "-inf"
            or float(maximum.group("value")) <= _SILENT_MAX_VOLUME_DB
        ):
            raise ExportTranscodeError("TRANSCODE_SILENT_OUTPUT")
        bytes_ = temporary.read_bytes()
        checksum = hashlib.sha256(bytes_).hexdigest()
        if cancel_event is not None and cancel_event.is_set():
            raise ExportTranscodeError("TRANSCODE_CANCELLED")
        final_key = (
            f"protected/exports/{project_id}/{revision_id}/audio/{checksum}-master.mp3"
            if revision_id is not None
            else (
                f"rebuildable/candidate-previews/{project_id}/{candidate_snapshot_id}/"
                f"{checksum}-preview.mp3"
            )
        )
        final = _safe(root, final_key)
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            promoted = promote_verified_file(
                source=temporary,
                final=final,
                expected_sha256=checksum,
                expected_bytes=len(bytes_),
                cancel_event=cancel_event,
            )
        except AtomicPromoteError as exc:
            code = str(exc)
            if code == "PROMOTE_IMMUTABLE_OUTPUT_CONFLICT":
                raise ExportTranscodeError("TRANSCODE_IMMUTABLE_OUTPUT_CONFLICT") from exc
            if code == "PROMOTE_CANCELLED":
                raise ExportTranscodeError("TRANSCODE_CANCELLED") from exc
            raise ExportTranscodeError("TRANSCODE_PROMOTION_FAILED", retryable=True) from exc
        created_new = promoted.created_new
        return Mp3TranscodeResult(
            storage_key=final_key,
            sha256=checksum,
            byte_size=len(bytes_),
            duration_seconds=duration,
            sample_rate_hz=sample_rate,
            channels=channels,
            bitrate_kbps=round(bitrate / 1000),
            created_new=created_new,
        )
    finally:
        temporary.unlink(missing_ok=True)
        with suppress(OSError):
            temporary.parent.rmdir()


def _run_process(
    args: list[str],
    *,
    timeout: int,
    cancel_event: threading.Event | None,
    text: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    if cancel_event is None:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=text,
            timeout=timeout,
        )
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event.is_set():
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise ExportTranscodeError("TRANSCODE_CANCELLED")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            process.communicate()
            raise subprocess.TimeoutExpired(args, timeout)
        try:
            stdout, stderr = process.communicate(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
