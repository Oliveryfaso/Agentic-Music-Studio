"""Controlled HTTP adapter for canonical Chromium/Tone render jobs."""

from __future__ import annotations

import hashlib
import shutil
import struct
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from motif_forge.audio.atomic_promote import AtomicPromoteError, promote_verified_file
from motif_forge.domain.media_jobs import (
    CandidatePreviewJobPayload,
    CandidatePreviewJobPayloadV4,
    CandidatePreviewJobPayloadV5,
    CanonicalRenderJobPayload,
    CanonicalRenderJobPayloadV4,
    CanonicalRenderJobPayloadV5,
)
from motif_forge.domain.render_capacity import estimate_render_capacity

RenderPayload = (
    CanonicalRenderJobPayload
    | CandidatePreviewJobPayload
    | CanonicalRenderJobPayloadV4
    | CandidatePreviewJobPayloadV4
    | CanonicalRenderJobPayloadV5
    | CandidatePreviewJobPayloadV5
)


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
    peak: float = Field(ge=0.0, le=1.0)


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


def _inspect_pcm24_wav(
    bytes_: bytes, *, file_size: int | None = None
) -> tuple[int, int, int, float]:
    if len(bytes_) < 44 or bytes_[0:4] != b"RIFF" or bytes_[8:12] != b"WAVE":
        raise ChromiumRenderError("RENDER_WAV_INVALID")
    channels, sample_rate = struct.unpack_from("<HI", bytes_, 22)
    bit_depth = struct.unpack_from("<H", bytes_, 34)[0]
    data_bytes = struct.unpack_from("<I", bytes_, 40)[0]
    if channels != 2 or sample_rate != 48_000 or bit_depth != 24:
        raise ChromiumRenderError("RENDER_MEDIA_PROFILE_INVALID")
    if data_bytes != (file_size if file_size is not None else len(bytes_)) - 44 or data_bytes % 6:
        raise ChromiumRenderError("RENDER_WAV_INVALID")
    return channels, sample_rate, bit_depth, data_bytes / 6 / sample_rate


def _expected_silence(payload: RenderPayload) -> bool:
    graph = payload.audio_graph
    schema_version = graph.get("schemaVersion")
    if schema_version not in ("audio-graph-spec.v4", "audio-graph-spec.v5"):
        return False
    engine_version = (
        "motif-forge-audio-engine.v5"
        if schema_version == "audio-graph-spec.v5"
        else "motif-forge-audio-engine.v4"
    )
    tracks = graph.get("tracks")
    if (
        graph.get("engineVersion") != engine_version
        or payload.audio_engine_version != engine_version
        or type(graph.get("expectedSilence")) is not bool
        or not isinstance(tracks, list)
        or not 1 <= len(tracks) <= 2
        or any(
            not isinstance(track, dict) or type(track.get("audible")) is not bool
            for track in tracks
        )
    ):
        raise ChromiumRenderError("RENDER_SILENCE_PROFILE_INVALID")
    if graph["expectedSilence"] != (not any(track["audible"] for track in tracks)):
        raise ChromiumRenderError("RENDER_SILENCE_PROFILE_INVALID")
    selected = {str(track_id) for track_id in payload.render_track_ids}
    if selected:
        available = {track.get("trackId") for track in tracks}
        if not selected.issubset(available):
            raise ChromiumRenderError("RENDER_SILENCE_PROFILE_INVALID")
        scoped = [track for track in tracks if track.get("trackId") in selected]
        if graph["expectedSilence"] != (not any(track["audible"] for track in scoped)):
            raise ChromiumRenderError("RENDER_SILENCE_PROFILE_INVALID")
    return graph["expectedSilence"] is True


class ChromiumRenderClient:
    def __init__(
        self,
        *,
        artifact_root: Path,
        temp_root: Path,
        service_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        minimum_free_bytes: int = 512 * 1024**2,
    ) -> None:
        self._root = artifact_root.resolve()
        self._temp_root = temp_root.resolve()
        self._service_url = service_url.rstrip("/")
        self._transport = transport
        if type(minimum_free_bytes) is not int or minimum_free_bytes < 0:
            raise ValueError("minimum_free_bytes must be nonnegative")
        self._minimum_free_bytes = minimum_free_bytes

    async def render(
        self,
        *,
        job_id: UUID,
        payload: RenderPayload,
    ) -> CanonicalRenderResult:
        if not self._root.is_dir():
            raise ChromiumRenderError("ARTIFACT_ROOT_UNAVAILABLE", retryable=True)
        if not self._temp_root.is_dir():
            raise ChromiumRenderError("TEMP_ROOT_UNAVAILABLE", retryable=True)
        try:
            capacity = estimate_render_capacity(payload.audio_graph)
        except ValueError as exc:
            raise ChromiumRenderError(str(exc)) from exc
        if payload.maximum_output_bytes < capacity.wav_bytes:
            raise ChromiumRenderError("RENDER_OUTPUT_BUDGET_EXCEEDED")
        bound = min(payload.maximum_output_bytes, capacity.output_limit_bytes)
        # Promotion may temporarily hold the source and final partial together.
        same_device = self._root.stat().st_dev == self._temp_root.stat().st_dev
        root_required = bound * (2 if same_device else 1) + self._minimum_free_bytes
        if (
            shutil.disk_usage(self._root).free < root_required
            or shutil.disk_usage(self._temp_root).free < root_required
        ):
            raise ChromiumRenderError("STORAGE_QUOTA_EXCEEDED")
        temporary = _safe_path(self._temp_root, f"jobs/{job_id}/render.wav")
        try:
            # Keep legacy payload serialization/recipes; only this execution's
            # effective sink is clamped to the calculated bounded allocation.
            return await self._render_to_file(
                job_id=job_id, payload=payload.model_copy(update={"maximum_output_bytes": bound})
            )
        finally:
            temporary.unlink(missing_ok=True)
            temporary.with_name(temporary.name + ".partial").unlink(missing_ok=True)
            with suppress(OSError):
                temporary.parent.rmdir()

    async def _render_to_file(
        self,
        *,
        job_id: UUID,
        payload: RenderPayload,
    ) -> CanonicalRenderResult:
        if not self._root.is_dir():
            raise ChromiumRenderError("ARTIFACT_ROOT_UNAVAILABLE", retryable=True)
        if not self._temp_root.is_dir():
            raise ChromiumRenderError("TEMP_ROOT_UNAVAILABLE", retryable=True)
        expected_silence = _expected_silence(payload)
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
            instrument_errors = {
                "INSTRUMENT_PACK_UNAVAILABLE",
                "INSTRUMENT_MANIFEST_HASH_MISMATCH",
                "INSTRUMENT_SAMPLE_HASH_MISMATCH",
                "INSTRUMENT_SAMPLE_SIZE_MISMATCH",
                "INSTRUMENT_POLYPHONY_EXCEEDED",
                "INSTRUMENT_NOTE_UNMAPPED",
                "INSTRUMENT_RESOURCE_LIMIT",
                "PIANO_RELEASE_OUT_OF_RANGE",
                "PIANO_PEDAL_UNSUPPORTED",
            }
            try:
                problem = exc.response.json()
            except ValueError:
                problem = None
            if isinstance(problem, dict) and problem.get("errorCode") in instrument_errors:
                raise ChromiumRenderError(problem["errorCode"], retryable=False) from exc
            retryable = exc.response.status_code in {408, 425, 429} or (
                exc.response.status_code >= 500
            )
            raise ChromiumRenderError("RENDER_SERVICE_FAILED", retryable=retryable) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ChromiumRenderError("RENDER_SERVICE_FAILED") from exc
        if receipt.receiptVersion != "render-service-receipt.v1":
            raise ChromiumRenderError("RENDER_RECEIPT_VERSION_INVALID")
        if receipt.requestId != str(job_id) or receipt.storageKey != temporary_key:
            raise ChromiumRenderError("RENDER_LINEAGE_MISMATCH")
        if receipt.peak == 0 and not expected_silence:
            raise ChromiumRenderError("RENDER_SILENT_OUTPUT")
        if expected_silence and receipt.peak != 0:
            raise ChromiumRenderError("RENDER_EXPECTED_SILENCE_MISMATCH")
        temporary = _safe_path(self._temp_root, temporary_key)
        try:
            file_size = temporary.stat().st_size
            if (
                file_size > payload.maximum_output_bytes
                or receipt.bytes > payload.maximum_output_bytes
            ):
                raise ChromiumRenderError("RENDER_OUTPUT_SIZE_EXCEEDED")
            with temporary.open("rb") as stream:
                header = stream.read(44)
                if expected_silence:
                    for chunk in iter(lambda: stream.read(64 * 1024), b""):
                        if any(chunk):
                            raise ChromiumRenderError("RENDER_EXPECTED_SILENCE_MISMATCH")
                stream.seek(0)
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if checksum != receipt.sha256 or file_size != receipt.bytes:
                raise ChromiumRenderError("RENDER_CHECKSUM_MISMATCH")
            channels, sample_rate, bit_depth, duration = _inspect_pcm24_wav(
                header, file_size=file_size
            )
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
