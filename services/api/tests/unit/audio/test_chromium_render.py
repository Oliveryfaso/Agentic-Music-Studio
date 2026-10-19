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


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "cancel", "invalid_receipt"])
async def test_client_cleans_job_files_when_request_never_yields_a_valid_receipt(tmp_path, kind):
    import asyncio
    import json

    (tmp_path / "temp").mkdir()

    async def handler(request):
        body = json.loads(request.content)
        output = tmp_path / "temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True)
        output.write_bytes(_pcm24_wav())
        output.with_name(output.name + ".partial").write_bytes(b"incomplete")
        if kind == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if kind == "cancel":
            raise asyncio.CancelledError
        return httpx.Response(200, json={"invalid": "receipt"})

    expected = asyncio.CancelledError if kind == "cancel" else ChromiumRenderError
    with pytest.raises(expected):
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "temp",
            service_url="http://render-worker:8090",
            transport=httpx.MockTransport(handler),
        ).render(job_id=JOB_ID, payload=_payload())
    assert not list((tmp_path / "temp").rglob("*.wav*"))
    assert not (tmp_path / "protected").exists()


@pytest.mark.asyncio
async def test_client_refuses_an_underfunded_pcm_budget_before_http(tmp_path):
    import json

    p = _payload()
    graph = {**p.audio_graph, "durationSeconds": 300}
    p = p.model_copy(
        update={
            "audio_graph": graph,
            "audio_graph_hash": hashlib.sha256(
                json.dumps(graph, separators=(",", ":"), sort_keys=True).encode()
            ).hexdigest(),
        }
    )
    (tmp_path / "temp").mkdir()

    async def forbidden(_):
        raise AssertionError("an underfunded render must not start")

    with pytest.raises(ChromiumRenderError, match="RENDER_OUTPUT_BUDGET_EXCEEDED"):
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "temp",
            service_url="http://render-worker:8090",
            transport=httpx.MockTransport(forbidden),
        ).render(job_id=JOB_ID, payload=p)


@pytest.mark.asyncio
async def test_client_refuses_insufficient_disk_before_http(tmp_path, monkeypatch):
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _: usage(100, 100, 0))
    (tmp_path / "temp").mkdir()

    async def forbidden(_):
        raise AssertionError("a full disk must not start a render")

    with pytest.raises(ChromiumRenderError, match="STORAGE_QUOTA_EXCEEDED"):
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "temp",
            service_url="http://render-worker:8090",
            transport=httpx.MockTransport(forbidden),
        ).render(job_id=JOB_ID, payload=_payload())


@pytest.mark.asyncio
async def test_client_rejects_oversized_temp_before_checksum_and_cleans_it(tmp_path):
    import json

    (tmp_path / "temp").mkdir()

    async def handler(request):
        body = json.loads(request.content)
        output = tmp_path / "temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True)
        with output.open("wb") as stream:
            stream.write(_pcm24_wav())
            stream.truncate(1_048_577)
        return httpx.Response(
            200,
            json={
                "receiptVersion": "render-service-receipt.v1",
                "requestId": str(JOB_ID),
                "storageKey": body["outputStorageKey"],
                "sha256": "0" * 64,
                "bytes": 1_048_577,
                "durationSeconds": 0.1,
                "sampleRate": 48000,
                "channels": 2,
                "bitDepth": 24,
                "peak": 0.1,
            },
        )

    with pytest.raises(ChromiumRenderError, match="RENDER_OUTPUT_SIZE_EXCEEDED"):
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "temp",
            service_url="http://render-worker:8090",
            transport=httpx.MockTransport(handler),
        ).render(job_id=JOB_ID, payload=_payload())
    assert not list((tmp_path / "temp").rglob("*.wav*"))


@pytest.mark.asyncio
async def test_client_preserves_explicit_missing_instrument_without_retry(tmp_path: Path) -> None:
    (tmp_path / "temp").mkdir()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errorCode": "INSTRUMENT_PACK_UNAVAILABLE"})

    client = ChromiumRenderClient(
        artifact_root=tmp_path,
        temp_root=tmp_path / "temp",
        service_url="http://local-test",
        transport=httpx.MockTransport(handler),
        minimum_free_bytes=0,
    )
    with pytest.raises(ChromiumRenderError, match="INSTRUMENT_PACK_UNAVAILABLE") as caught:
        await client.render(job_id=JOB_ID, payload=_payload())
    assert not caught.value.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("version", "audible", "expected_silence", "peak", "accept"),
    [
        (4, False, True, 0.0, True),
        (4, True, False, 0.0, False),
        (4, True, True, 0.0, False),
        (4, False, False, 0.0, False),
        (4, 0, True, 0.0, False),
        (4, False, 1, 0.0, False),
        (4, False, True, 0.1, False),
        (5, False, True, 0.0, True),
        (5, True, False, 0.0, False),
        (5, True, True, 0.0, False),
        (5, False, False, 0.0, False),
        (5, 0, True, 0.0, False),
        (5, False, 1, 0.0, False),
        (5, False, True, 0.1, False),
        (3, False, True, 0.0, False),
    ],
)
async def test_expected_silence_receipt_requires_exact_versioned_mix(
    tmp_path, version, audible, expected_silence, peak, accept
):
    import json

    payload = _payload()
    graph = {
        **payload.audio_graph,
        "schemaVersion": f"audio-graph-spec.v{version}",
        "engineVersion": f"motif-forge-audio-engine.v{version}",
        "expectedSilence": expected_silence,
        "tracks": [{**payload.audio_graph["tracks"][0], "audible": audible}],
    }
    payload = payload.model_copy(
        update={"audio_graph": graph, "audio_engine_version": graph["engineVersion"]}
    )
    (tmp_path / "temp").mkdir()
    raw = _pcm24_wav()
    wav = raw[:44] + bytes(len(raw) - 44)

    async def handler(request):
        body = json.loads(request.content)
        output = tmp_path / "temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True)
        output.write_bytes(wav)
        return httpx.Response(
            200,
            json={
                "receiptVersion": "render-service-receipt.v1",
                "requestId": str(JOB_ID),
                "storageKey": body["outputStorageKey"],
                "sha256": hashlib.sha256(wav).hexdigest(),
                "bytes": len(wav),
                "durationSeconds": 0.1,
                "sampleRate": 48000,
                "channels": 2,
                "bitDepth": 24,
                "peak": peak,
            },
        )

    client = ChromiumRenderClient(
        artifact_root=tmp_path,
        temp_root=tmp_path / "temp",
        service_url="http://test",
        transport=httpx.MockTransport(handler),
        minimum_free_bytes=0,
    )
    if accept:
        result = await client.render(job_id=JOB_ID, payload=payload)
        assert result.peak == 0
        assert (tmp_path / result.storage_key).read_bytes()[44:] == bytes(len(wav) - 44)
    else:
        with pytest.raises(ChromiumRenderError):
            await client.render(job_id=JOB_ID, payload=payload)
        assert not (tmp_path / "protected").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [4, 5])
async def test_expected_silence_rejects_nonzero_pcm_even_when_receipt_says_zero(tmp_path, version):
    import json

    payload = _payload()
    graph = {
        **payload.audio_graph,
        "schemaVersion": f"audio-graph-spec.v{version}",
        "engineVersion": f"motif-forge-audio-engine.v{version}",
        "expectedSilence": True,
        "tracks": [{**payload.audio_graph["tracks"][0], "audible": False}],
    }
    payload = payload.model_copy(
        update={"audio_graph": graph, "audio_engine_version": graph["engineVersion"]}
    )
    (tmp_path / "temp").mkdir()
    wav = _pcm24_wav()

    async def handler(request):
        body = json.loads(request.content)
        output = tmp_path / "temp" / body["outputStorageKey"]
        output.parent.mkdir(parents=True)
        output.write_bytes(wav)
        return httpx.Response(
            200,
            json={
                "receiptVersion": "render-service-receipt.v1",
                "requestId": str(JOB_ID),
                "storageKey": body["outputStorageKey"],
                "sha256": hashlib.sha256(wav).hexdigest(),
                "bytes": len(wav),
                "durationSeconds": 0.1,
                "sampleRate": 48000,
                "channels": 2,
                "bitDepth": 24,
                "peak": 0.0,
            },
        )

    with pytest.raises(ChromiumRenderError, match="RENDER_EXPECTED_SILENCE_MISMATCH"):
        await ChromiumRenderClient(
            artifact_root=tmp_path,
            temp_root=tmp_path / "temp",
            service_url="http://test",
            transport=httpx.MockTransport(handler),
            minimum_free_bytes=0,
        ).render(job_id=JOB_ID, payload=payload)


@pytest.mark.parametrize(
    "tamper", ["graph-engine", "payload-engine", "unknown-scope", "muted-scope"]
)
def test_v5_adapter_does_not_relax_silence_for_mismatched_version_or_scope(tamper):
    from motif_forge.audio.chromium_render import _expected_silence

    payload = _payload()
    audible_id, muted_id = UUID(int=60), UUID(int=61)
    graph = {
        **payload.audio_graph,
        "schemaVersion": "audio-graph-spec.v5",
        "engineVersion": "motif-forge-audio-engine.v5",
        "expectedSilence": False,
        "tracks": [
            {"trackId": str(audible_id), "audible": True},
            {"trackId": str(muted_id), "audible": False},
        ],
    }
    updates = {"audio_graph": graph, "audio_engine_version": "motif-forge-audio-engine.v5"}
    if tamper == "graph-engine":
        graph["engineVersion"] = "motif-forge-audio-engine.v4"
    if tamper == "payload-engine":
        updates["audio_engine_version"] = "motif-forge-audio-engine.v4"
    if tamper == "unknown-scope":
        updates["render_track_ids"] = (UUID(int=62),)
    if tamper == "muted-scope":
        updates["render_track_ids"] = (muted_id,)
    with pytest.raises(ChromiumRenderError, match="RENDER_SILENCE_PROFILE_INVALID"):
        _expected_silence(payload.model_copy(update=updates))
