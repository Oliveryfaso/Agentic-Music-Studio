"""Read the renderer's actually admitted catalog; no paths or model calls in UI."""

from __future__ import annotations

from typing import Literal

import httpx
from pydantic import Field

from motif_forge.domain.ir import DomainModel, PianoRenderProfile


class PianoCapability(DomainModel):
    available: bool
    render_profile: PianoRenderProfile = Field(default_factory=PianoRenderProfile)
    pedal_supported: Literal[False] = False
    release_triggers_supported: Literal[False] = False
    error_code: str | None = None


class ReadPianoCapability:
    def __init__(
        self, *, service_url: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._url, self._transport = service_url.rstrip("/"), transport

    async def __call__(self) -> PianoCapability:
        profile = PianoRenderProfile()
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=2.0, trust_env=False
            ) as client:
                response = await client.get(self._url + "/health")
                response.raise_for_status()
                value = response.json()
        except (httpx.HTTPError, ValueError):
            return PianoCapability(available=False, error_code="RENDER_SERVICE_UNAVAILABLE")
        expected = {
            "packId": profile.instrument_pack_id,
            "packVersion": profile.instrument_pack_version,
            "manifestSha256": profile.manifest_sha256,
        }
        available = (
            isinstance(value, dict)
            and value.get("status") == "ready"
            and isinstance(value.get("instrumentPacks"), list)
            and expected in value["instrumentPacks"]
        )
        return PianoCapability(
            available=available, error_code=None if available else "INSTRUMENT_PACK_UNAVAILABLE"
        )
