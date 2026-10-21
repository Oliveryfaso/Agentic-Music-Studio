from __future__ import annotations

import httpx
import pytest
from motif_forge.application.piano_capability import ReadPianoCapability
from motif_forge.domain.ir import PianoRenderProfile


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [True, False])
async def test_capability_uses_actual_admitted_catalog_without_exposing_paths(ready: bool) -> None:
    profile = PianoRenderProfile()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "concurrency": 1,
                "instrumentPacks": (
                    [
                        {
                            "packId": profile.instrument_pack_id,
                            "packVersion": profile.instrument_pack_version,
                            "manifestSha256": profile.manifest_sha256,
                        }
                    ]
                    if ready
                    else []
                ),
            },
        )

    value = await ReadPianoCapability(
        service_url="http://local-renderer", transport=httpx.MockTransport(handler)
    )()
    assert value.available is ready
    assert value.error_code is None if ready else value.error_code == "INSTRUMENT_PACK_UNAVAILABLE"
    assert not value.pedal_supported and not value.release_triggers_supported
    assert "root" not in value.model_dump_json()
    assert value.semantic_generation.model_dump() == {
        "configuration": "unknown", "reason_code": None
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured", "configuration", "reason_code"),
    [
        (True, "configured", None),
        (False, "not_configured", "MODEL_NOT_CONFIGURED"),
        (None, "unknown", None),
    ],
)
@pytest.mark.parametrize(
    ("renderer", "available", "error_code"),
    [
        ("ready", True, None),
        ("missing_pack", False, "INSTRUMENT_PACK_UNAVAILABLE"),
        ("http_error", False, "RENDER_SERVICE_UNAVAILABLE"),
        ("bad_json", False, "RENDER_SERVICE_UNAVAILABLE"),
        ("transport_error", False, "RENDER_SERVICE_UNAVAILABLE"),
    ],
)
async def test_model_configuration_stays_independent_of_renderer_health(
    configured: bool | None,
    configuration: str,
    reason_code: str | None,
    renderer: str,
    available: bool,
    error_code: str | None,
) -> None:
    profile = PianoRenderProfile()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/health"
        if renderer == "transport_error":
            raise httpx.ConnectError("private-renderer-diagnostic", request=request)
        if renderer == "http_error":
            return httpx.Response(503, json={"error": "private-renderer-diagnostic"})
        if renderer == "bad_json":
            return httpx.Response(200, content=b"private-renderer-diagnostic")
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "concurrency": 1,
                "internal_url": "https://private-renderer-diagnostic.invalid",
                "instrumentPacks": [
                    {
                        "packId": profile.instrument_pack_id,
                        "packVersion": profile.instrument_pack_version,
                        "manifestSha256": profile.manifest_sha256,
                    }
                ] if renderer == "ready" else [],
            },
        )

    value = await ReadPianoCapability(
        service_url="http://local-renderer",
        transport=httpx.MockTransport(handler),
        semantic_generation_configured=configured,
    )()

    assert value.available is available
    assert value.error_code == error_code
    assert value.semantic_generation.model_dump() == {
        "configuration": configuration, "reason_code": reason_code
    }
    serialized = value.model_dump_json()
    assert "local-renderer" not in serialized
    assert "private-renderer-diagnostic" not in serialized
