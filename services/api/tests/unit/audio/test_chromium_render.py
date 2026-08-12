from __future__ import annotations

import errno
import hashlib
import os
import struct
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.audio.chromium_render import (
    ChromiumRenderClient,
    ChromiumRenderError,
)
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.media_jobs import (
    CanonicalRenderJobPayload,
    MediaQualityProfile,
    RenderScope,
)

PROJECT_ID = UUID("10000000-0000-4000-8000-000000000044")
REVISION_ID = UUID("20000000-0000-4000-8000-000000000044")
JOB_ID = UUID("30000000-0000-4000-8000-000000000044")


def _pcm24_wav(*, seconds: float = 0.1, sample_rate: int = 48_000) -> bytes:
    frames = round(seconds * sample_rate)
    data = b"".join(struct.pack("<i", 100_000)[0:3] * 2 for _ in range(frames))
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 2, sample_rate, sample_rate * 6, 6, 24)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def _payload() -> CanonicalRenderJobPayload:
    arrangement = build_s1_composition(PROJECT_ID, seed=44).arrangement
    projection = compile_audio_graph(arrangement)
    graph = {**projection.graph, "durationSeconds": 0.1}
    import json

    graph_hash = hashlib.sha256(
        json.dumps(graph, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return CanonicalRenderJobPayload(
        project_id=PROJECT_ID,
        revision_id=REVISION_ID,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        audio_graph=graph,
        audio_graph_hash=graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version="motif-forge-audio-engine.v1",
        seed=44,
        timeout_seconds=30,
        maximum_output_bytes=1_048_576,
    )


@pytest.mark.asyncio
async def test_client_validates_receipt_pcm24_checksum_and_promotes_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    (tmp_path / "explicit-temp").mkdir()
    wav = _pcm24_wav()
    checksum = hashlib.sha256(wav).hexdigest()
    real_replace = os.replace

    def reject_cross_device_replace(source: Path | str, target: Path | str) -> None:
        if Path(source).is_relative_to(tmp_path / "explicit-temp") and Path(target).is_relative_to(
            tmp_path / "protected"
        ):
            raise OSError(errno.EXDEV, "cross-device link")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", reject_cross_device_replace)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        output = tmp_path / "explicit-temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True)
        output.write_bytes(wav)
        return httpx.Response(
            200,
            json={
                "receiptVersion": "render-service-receipt.v1",
                "requestId": str(JOB_ID),
                "storageKey": body["outputStorageKey"],
                "sha256": checksum,
                "bytes": len(wav),
                "durationSeconds": 0.1,
                "sampleRate": 48_000,
                "channels": 2,
                "bitDepth": 24,
                "peak": 0.012,
            },
        )

    result = await ChromiumRenderClient(
        artifact_root=tmp_path,
        temp_root=tmp_path / "explicit-temp",
        service_url="http://render-worker:8090",
        transport=httpx.MockTransport(handler),
    ).render(job_id=JOB_ID, payload=payload)

    assert result.sha256 == checksum
    assert result.bit_depth == 24
    assert result.duration_seconds == pytest.approx(0.1)
    assert result.created_new is True
    assert result.storage_key.endswith(f"/{checksum}-master.wav")
    assert (tmp_path / result.storage_key).read_bytes() == wav
    assert not (tmp_path / "tmp").exists()
    assert not (tmp_path / "explicit-temp" / "jobs" / str(JOB_ID) / "render.wav").exists()


@pytest.mark.asyncio
async def test_client_rejects_checksum_mismatch_without_promoting(tmp_path: Path) -> None:
    payload = _payload()
    (tmp_path / "explicit-temp").mkdir()
    wav = _pcm24_wav()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        output = tmp_path / "explicit-temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True)
        output.write_bytes(wav)
        return httpx.Response(
            200,
            json={
                "receiptVersion": "render-service-receipt.v1",
                "requestId": str(JOB_ID),
                "storageKey": body["outputStorageKey"],
                "sha256": "0" * 64,
                "bytes": len(wav),
                "durationSeconds": 0.1,
                "sampleRate": 48_000,
                "channels": 2,
                "bitDepth": 24,
                "peak": 0.012,
            },
        )

    with pytest.raises(ChromiumRenderError, match="RENDER_CHECKSUM_MISMATCH"):
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "explicit-temp",
            service_url="http://render-worker:8090",
            transport=httpx.MockTransport(handler),
        ).render(job_id=JOB_ID, payload=payload)


@pytest.mark.asyncio
async def test_client_refuses_to_overwrite_content_addressed_output(tmp_path: Path) -> None:
    payload = _payload()
    (tmp_path / "explicit-temp").mkdir()
    wav = _pcm24_wav()
    checksum = hashlib.sha256(wav).hexdigest()
    target = (
        tmp_path
        / "protected"
        / "exports"
        / str(PROJECT_ID)
        / str(REVISION_ID)
        / "audio"
        / f"{checksum}-master.wav"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different bytes")

    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        output = tmp_path / "explicit-temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(wav)
        return httpx.Response(
            200,
            json={
                "receiptVersion": "render-service-receipt.v1",
                "requestId": str(JOB_ID),
                "storageKey": body["outputStorageKey"],
                "sha256": checksum,
                "bytes": len(wav),
                "durationSeconds": 0.1,
                "sampleRate": 48_000,
                "channels": 2,
                "bitDepth": 24,
                "peak": 0.012,
            },
        )

    with pytest.raises(ChromiumRenderError, match="RENDER_IMMUTABLE_OUTPUT_CONFLICT"):
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "explicit-temp",
            service_url="http://render-worker:8090",
            transport=httpx.MockTransport(handler),
        ).render(job_id=JOB_ID, payload=payload)
    assert target.read_bytes() == b"different bytes"


@pytest.mark.asyncio
async def test_client_classifies_service_disconnect_as_retryable(tmp_path: Path) -> None:
    (tmp_path / "explicit-temp").mkdir()

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("render worker disconnected", request=request)

    with pytest.raises(ChromiumRenderError) as captured:
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "explicit-temp",
            service_url="http://render-worker:8090",
            transport=httpx.MockTransport(handler),
        ).render(job_id=JOB_ID, payload=_payload())

    assert captured.value.code == "RENDER_SERVICE_UNAVAILABLE"
    assert captured.value.retryable


@pytest.mark.asyncio
async def test_client_rejects_unavailable_artifact_root_before_render(tmp_path: Path) -> None:
    missing_root = tmp_path / "disconnected-external-volume"

    with pytest.raises(ChromiumRenderError) as captured:
        await ChromiumRenderClient(
            artifact_root=missing_root,
            temp_root=tmp_path / "explicit-temp",
            service_url="http://render-worker:8090",
        ).render(job_id=JOB_ID, payload=_payload())

    assert captured.value.code == "ARTIFACT_ROOT_UNAVAILABLE"
    assert captured.value.retryable


@pytest.mark.asyncio
async def test_client_does_not_use_host_proxy_for_internal_render_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compose peer traffic must bypass inherited host proxy variables."""
    payload = _payload()
    (tmp_path / "explicit-temp").mkdir()
    wav = _pcm24_wav()
    checksum = hashlib.sha256(wav).hexdigest()
    seen_extensions: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_extensions.append(dict(request.extensions))
        body = __import__("json").loads(request.content)
        output = tmp_path / "explicit-temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True)
        output.write_bytes(wav)
        return httpx.Response(
            200,
            json={
                "receiptVersion": "render-service-receipt.v1",
                "requestId": str(JOB_ID),
                "storageKey": body["outputStorageKey"],
                "sha256": checksum,
                "bytes": len(wav),
                "durationSeconds": 0.1,
                "sampleRate": 48_000,
                "channels": 2,
                "bitDepth": 24,
                "peak": 0.012,
            },
        )

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    result = await ChromiumRenderClient(
        artifact_root=tmp_path,
        temp_root=tmp_path / "explicit-temp",
        service_url="http://render-worker:8090",
        transport=httpx.MockTransport(handler),
    ).render(job_id=JOB_ID, payload=payload)

    assert result.sha256 == checksum
    assert seen_extensions
