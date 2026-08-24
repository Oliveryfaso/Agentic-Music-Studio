import pytest
from httpx import ASGITransport, AsyncClient
from motif_forge.api.app import create_app
from motif_forge.config import Settings


@pytest.mark.asyncio
async def test_sound_catalog_route_filters_reviewed_local_entries() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(Settings.for_test())),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/sound-catalog?style=jazz_harmony_improvisation&role=bass&query=bass"
        )
    assert response.status_code == 200
    assert response.json()["data"]
    assert all(item["preset_id"].startswith("builtin:") for item in response.json()["data"])
