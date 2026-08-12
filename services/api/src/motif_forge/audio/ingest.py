"""Deterministic decode validation and normalization for quarantined source audio."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from motif_forge.audio.analysis import analyze_imported_audio
from motif_forge.audio.features import FeatureOutput, write_import_features
from motif_forge.domain.media_jobs import ImportedAudioAnalysis


class AudioIngestError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{code}: {message}")


class AudioProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    codec: str = Field(min_length=1, max_length=40)
    sample_rate_hz: int = Field(ge=8_000, le=192_000)
    channels: int = Field(ge=1, le=8)
    duration_seconds: float = Field(gt=0.0, le=1800.0, allow_inf_nan=False)
    bitrate_kbps: int | None = Field(default=None, ge=32, le=1536)
    bit_depth: int | None = Field(default=None, ge=8, le=64)


@dataclass(frozen=True, slots=True)
class NormalizedAudio:
    storage_key: str
    sha256: str
    byte_size: int
    probe: AudioProbe
    recipe_hash: str
    engine_version: str
    analysis: ImportedAudioAnalysis
    feature_outputs: tuple[FeatureOutput, FeatureOutput]


class LocalAudioIngestor:
    def __init__(self, artifact_root: Path, *, ffmpeg_binary: str = "ffmpeg") -> None:
        self._root = artifact_root.expanduser().resolve()
        self._ffmpeg = ffmpeg_binary

    def run(
        self,
        *,
        job_id: UUID,
        project_id: UUID,
        source_storage_key: str,
        source_hash: str,
        timeout_seconds: float,
    ) -> tuple[AudioProbe, NormalizedAudio]:
        source = self._resolve_key(source_storage_key)
        if not source.is_file() or source.is_symlink():
            raise AudioIngestError(
                "SOURCE_ARTIFACT_UNAVAILABLE", "the uploaded source bytes are unavailable"
            )
        if _sha256_file(source) != source_hash:
            raise AudioIngestError(
                "SOURCE_ARTIFACT_CHECKSUM_MISMATCH", "the uploaded source checksum changed"
            )
        source_probe = self._probe(source, timeout_seconds)
        recipe_payload = {
            "schema": "audio-ingest-recipe.v1",
            "source_hash": source_hash,
            "sample_rate_hz": 48_000,
            "channels": 2,
            "codec": "pcm_s16le",
            "engine": self._ffmpeg,
        }
        recipe_hash = hashlib.sha256(
            json.dumps(recipe_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        scratch = self._resolve_key(f"tmp/jobs/{job_id}")
        scratch.mkdir(parents=True, exist_ok=True)
        pending = scratch / "normalized.wav.pending"
        try:
            command = [
                self._ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                str(pending),
            ]
            _run_checked(command, timeout_seconds)
            output_probe = self._probe(pending, timeout_seconds)
            if (
                output_probe.codec not in {"pcm_s16le", "pcm"}
                or output_probe.sample_rate_hz != 48_000
                or output_probe.channels != 2
                or output_probe.bit_depth != 16
            ):
                raise AudioIngestError(
                    "INGEST_OUTPUT_MEDIA_INVALID", "normalized audio failed the PCM16 contract"
                )
            checksum = _sha256_file(pending)
            analysis = analyze_imported_audio(pending)
            storage_key = f"protected/working-pcm/{project_id}/{checksum[:2]}/{checksum}.wav"
            destination = self._resolve_key(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.is_symlink() or _sha256_file(destination) != checksum:
                    raise AudioIngestError(
                        "ARTIFACT_HASH_COLLISION", "existing normalized Artifact failed checksum"
                    )
                pending.unlink()
            else:
                os.replace(pending, destination)
            feature_outputs = write_import_features(
                destination,
                artifact_root=self._root,
                project_id=project_id,
                source_content_hash=checksum,
                analysis=analysis,
            )
            return source_probe, NormalizedAudio(
                storage_key=storage_key,
                sha256=checksum,
                byte_size=destination.stat().st_size,
                probe=output_probe,
                recipe_hash=recipe_hash,
                engine_version=self._engine_version(),
                analysis=analysis,
                feature_outputs=feature_outputs,
            )
        except OSError as exc:
            raise AudioIngestError(
                "ARTIFACT_ROOT_UNAVAILABLE",
                "the external Artifact Root became unavailable",
                retryable=True,
            ) from exc
        finally:
            if pending.exists():
                pending.unlink()

    def _probe(self, path: Path, timeout_seconds: float) -> AudioProbe:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,duration,bit_rate,bits_per_sample,bits_per_raw_sample",
            "-of",
            "json",
            str(path),
        ]
        result = _run_checked(command, timeout_seconds)
        try:
            streams = json.loads(result.stdout)["streams"]
            if len(streams) != 1:
                raise ValueError
            stream = streams[0]
            duration = float(stream["duration"])
            raw_bit_depth = stream.get("bits_per_raw_sample") or stream.get("bits_per_sample")
            bit_depth = int(raw_bit_depth) if raw_bit_depth and int(raw_bit_depth) > 0 else None
            raw_bitrate = stream.get("bit_rate")
            bitrate = round(int(raw_bitrate) / 1000) if raw_bitrate else None
            if str(stream["codec_name"]).startswith("pcm_"):
                bitrate = None
            return AudioProbe(
                codec=str(stream["codec_name"]),
                sample_rate_hz=int(stream["sample_rate"]),
                channels=int(stream["channels"]),
                duration_seconds=duration,
                bitrate_kbps=bitrate,
                bit_depth=bit_depth,
            )
        except ValidationError as exc:
            raise AudioIngestError(
                "AUDIO_RESOURCE_LIMIT_EXCEEDED",
                "decoded audio exceeds the supported duration or media bounds",
            ) from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AudioIngestError(
                "AUDIO_DECODE_INVALID", "FFprobe could not decode one supported audio stream"
            ) from exc

    def _resolve_key(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise AudioIngestError("SOURCE_ARTIFACT_KEY_INVALID", "unsafe Artifact storage key")
        resolved = (self._root / key).resolve()
        if not resolved.is_relative_to(self._root):
            raise AudioIngestError("SOURCE_ARTIFACT_KEY_INVALID", "unsafe Artifact storage key")
        return resolved

    def _engine_version(self) -> str:
        result = _run_checked([self._ffmpeg, "-version"], 10.0)
        return result.stdout.splitlines()[0][:80]


def _run_checked(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise AudioIngestError("MEDIA_ENGINE_UNAVAILABLE", "FFmpeg is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioIngestError(
            "AUDIO_INGEST_TIMEOUT", "audio ingest exceeded its deadline", retryable=True
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise AudioIngestError(
            "AUDIO_DECODE_INVALID", "the source audio could not be decoded"
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
