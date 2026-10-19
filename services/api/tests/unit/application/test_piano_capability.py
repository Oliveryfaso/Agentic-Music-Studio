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
