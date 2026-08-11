import pytest
from httpx import ASGITransport, AsyncClient
from motif_forge.api.app import create_app
from motif_forge.config import Settings


@pytest.mark.asyncio
async def test_live_health() -> None:
    transport = ASGITransport(app=create_app(Settings(environment="test")))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "live"


@pytest.mark.asyncio
async def test_readiness_does_not_claim_connectivity() -> None:
    settings = Settings(
        environment="test",
        postgres_dsn="postgresql://example.invalid/db",
        redis_url="redis://example.invalid/0",
    )

    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "postgres": {"configured": True, "connectivity": "not_checked"},
        "redis": {"configured": True, "connectivity": "not_checked"},
    }


@pytest.mark.asyncio
async def test_deepseek_secret_is_not_exposed_by_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    settings = Settings(environment="test")

    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert "test-secret" not in response.text
    assert settings.deepseek_api_key is not None
