"""Controlled HTTP adapter for canonical Chromium/Tone render jobs."""

from __future__ import annotations

import hashlib
import struct
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from motif_forge.audio.atomic_promote import AtomicPromoteError, promote_verified_file
from motif_forge.domain.media_jobs import CandidatePreviewJobPayload, CanonicalRenderJobPayload


class ChromiumRenderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class RenderServiceReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    receiptVersion: str
    requestId: str
    storageKey: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=44)
    durationSeconds: float = Field(gt=0.0, le=300.0)
    sampleRate: int
    channels: int
    bitDepth: int
    peak: float = Field(gt=0.0, le=1.0)


@dataclass(frozen=True, slots=True)
class CanonicalRenderResult:
    storage_key: str
    sha256: str
    byte_size: int
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    bit_depth: int
    peak: float
    created_new: bool


def _safe_path(root: Path, storage_key: str) -> Path:
    if storage_key.startswith("/") or ".." in storage_key.split("/"):
        raise ChromiumRenderError("RENDER_OUTPUT_KEY_INVALID")
    resolved_root = root.resolve()
    output = (resolved_root / storage_key).resolve()
    if not output.is_relative_to(resolved_root):
        raise ChromiumRenderError("RENDER_OUTPUT_KEY_INVALID")
    return output


def _inspect_pcm24_wav(bytes_: bytes) -> tuple[int, int, int, float]:
    if len(bytes_) < 44 or bytes_[0:4] != b"RIFF" or bytes_[8:12] != b"WAVE":
        raise ChromiumRenderError("RENDER_WAV_INVALID")
    channels, sample_rate = struct.unpack_from("<HI", bytes_, 22)
    bit_depth = struct.unpack_from("<H", bytes_, 34)[0]
    data_bytes = struct.unpack_from("<I", bytes_, 40)[0]
    if channels != 2 or sample_rate != 48_000 or bit_depth != 24:
        raise ChromiumRenderError("RENDER_MEDIA_PROFILE_INVALID")
    if data_bytes != len(bytes_) - 44 or data_bytes % 6:
        raise ChromiumRenderError("RENDER_WAV_INVALID")
    return channels, sample_rate, bit_depth, data_bytes / 6 / sample_rate


class ChromiumRenderClient:
    def __init__(
        self,
        *,
        artifact_root: Path,
        temp_root: Path,
        service_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._root = artifact_root.resolve()
        self._temp_root = temp_root.resolve()
        self._service_url = service_url.rstrip("/")
        self._transport = transport

    async def render(
        self,
        *,
        job_id: UUID,
        payload: CanonicalRenderJobPayload | CandidatePreviewJobPayload,
    ) -> CanonicalRenderResult:
        if not self._root.is_dir():
            raise ChromiumRenderError("ARTIFACT_ROOT_UNAVAILABLE", retryable=True)
        if not self._temp_root.is_dir():
            raise ChromiumRenderError("TEMP_ROOT_UNAVAILABLE", retryable=True)
        temporary_key = f"jobs/{job_id}/render.wav"
        request = {
            "requestVersion": "render-service-request.v1",
            "requestId": str(job_id),
            "outputStorageKey": temporary_key,
            "maximumBytes": payload.maximum_output_bytes,
            "timeoutMs": payload.timeout_seconds * 1000,
            "bridgeRequest": {
                "requestVersion": "render-bridge-request.v1",
                "requestId": str(job_id),
                "outputToken": "0" * 32,
                "outputBitDepth": 24,
                "graph": payload.audio_graph,
                **(
                    {"renderTrackIds": [str(item) for item in payload.render_track_ids]}
                    if payload.render_track_ids
                    else {}
                ),
            },
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(payload.timeout_seconds + 5),
                # The render service is an internal Compose peer. Host proxy variables
                # must never route this request outside the project network.
                trust_env=False,
            ) as client:
                response = await client.post(f"{self._service_url}/v1/render", json=request)
                response.raise_for_status()
                receipt = RenderServiceReceipt.model_validate(response.json(), strict=True)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise ChromiumRenderError("RENDER_SERVICE_UNAVAILABLE", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in {408, 425, 429} or (
                exc.response.status_code >= 500
            )
            raise ChromiumRenderError(
                "RENDER_SERVICE_FAILED", retryable=retryable
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ChromiumRenderError("RENDER_SERVICE_FAILED") from exc
        if receipt.receiptVersion != "render-service-receipt.v1":
            raise ChromiumRenderError("RENDER_RECEIPT_VERSION_INVALID")
        if receipt.requestId != str(job_id) or receipt.storageKey != temporary_key:
            raise ChromiumRenderError("RENDER_LINEAGE_MISMATCH")
        temporary = _safe_path(self._temp_root, temporary_key)
        try:
            bytes_ = temporary.read_bytes()
            checksum = hashlib.sha256(bytes_).hexdigest()
            if checksum != receipt.sha256 or len(bytes_) != receipt.bytes:
                raise ChromiumRenderError("RENDER_CHECKSUM_MISMATCH")
            channels, sample_rate, bit_depth, duration = _inspect_pcm24_wav(bytes_)
            tolerance = 1 / sample_rate
            if (
                abs(duration - receipt.durationSeconds) > tolerance
                or receipt.sampleRate != sample_rate
                or receipt.channels != channels
                or receipt.bitDepth != bit_depth
            ):
                raise ChromiumRenderError("RENDER_RECEIPT_MEDIA_MISMATCH")
            expected_duration = float(payload.audio_graph["durationSeconds"])
            if abs(duration - expected_duration) > tolerance:
                raise ChromiumRenderError("RENDER_DURATION_MISMATCH")
            if isinstance(payload, CandidatePreviewJobPayload):
                final_key = (
                    f"rebuildable/candidate-previews/{payload.project_id}/"
                    f"{payload.candidate_snapshot_id}/{receipt.sha256}-source.wav"
                )
            else:
                suffix = (
                    f"stem-{payload.render_track_ids[0]}.wav"
                    if payload.render_track_ids
                    else "master.wav"
                )
                final_key = (
                    f"protected/exports/{payload.project_id}/{payload.revision_id}/audio/"
                    f"{receipt.sha256}-{suffix}"
                )
            final = _safe_path(self._root, final_key)
            final.parent.mkdir(parents=True, exist_ok=True)
            try:
                promoted = promote_verified_file(
                    source=temporary,
                    final=final,
                    expected_sha256=receipt.sha256,
                    expected_bytes=receipt.bytes,
                )
            except AtomicPromoteError as exc:
                if str(exc) == "PROMOTE_IMMUTABLE_OUTPUT_CONFLICT":
                    raise ChromiumRenderError("RENDER_IMMUTABLE_OUTPUT_CONFLICT") from exc
                raise ChromiumRenderError("RENDER_PROMOTION_FAILED", retryable=True) from exc
            created_new = promoted.created_new
        finally:
            if temporary.exists():
                temporary.unlink()
            with suppress(OSError):
                temporary.parent.rmdir()
        return CanonicalRenderResult(
            storage_key=final_key,
            sha256=receipt.sha256,
            byte_size=receipt.bytes,
            duration_seconds=duration,
            sample_rate_hz=sample_rate,
            channels=channels,
            bit_depth=bit_depth,
            peak=receipt.peak,
            created_new=created_new,
        )
