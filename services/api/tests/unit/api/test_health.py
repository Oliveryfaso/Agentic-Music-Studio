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
async def test_readiness_reports_real_connectivity() -> None:
    settings = Settings(
        environment="test",
        postgres_dsn="postgresql://example.invalid/db",
        redis_url="redis://example.invalid/0",
    )

    async def connected() -> bool:
        return True

    transport = ASGITransport(
        app=create_app(
            settings,
            readiness_probes={
                "postgres": connected,
                "redis": connected,
                "artifact_root": connected,
            },
        )
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "postgres": {"configured": True, "connectivity": "connected"},
        "redis": {"configured": True, "connectivity": "connected"},
        "artifact_root": {"configured": True, "connectivity": "connected"},
    }


@pytest.mark.asyncio
async def test_readiness_fails_closed_when_dependency_is_unconfigured() -> None:
    transport = ASGITransport(
        app=create_app(Settings(environment="test", postgres_dsn=None, redis_url=None))
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["postgres"]["connectivity"] == "not_configured"


@pytest.mark.asyncio
async def test_readiness_fails_closed_on_probe_error() -> None:
    settings = Settings(
        environment="test",
        postgres_dsn="postgresql://example.invalid/db",
        redis_url="redis://example.invalid/0",
    )

    async def connected() -> bool:
        return True

    async def failed() -> bool:
        raise ConnectionError("not exposed")

    transport = ASGITransport(
        app=create_app(
            settings,
            readiness_probes={
                "postgres": connected,
                "redis": failed,
                "artifact_root": connected,
            },
        )
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == {
        "configured": True,
        "connectivity": "failed",
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


def test_openapi_exposes_import_run_audio_and_feature_read_routes() -> None:
    paths = create_app(Settings(environment="test")).openapi()["paths"]

    assert "/api/v1/audio-artifacts/{artifact_id}/features" in paths
    assert "/api/v1/audio-artifacts/{artifact_id}/content" in paths
    assert "/api/v1/feature-artifacts/{artifact_id}" in paths
    assert "/api/v1/imports/{thread_id}" in paths
