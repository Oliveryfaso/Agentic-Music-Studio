"""No network: deployment boundary of the additive model-settings API."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from motif_forge.api.model_settings import build_model_settings_router
from motif_forge.config import Settings
from pydantic import SecretStr

KEY = "synthetic-boundary-key-not-real"


def api(key=None):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"object": "list", "data": []})

    app = FastAPI()
    app.include_router(
        build_model_settings_router(
            Settings.for_test(
                deepseek_api_key=SecretStr(key) if key is not None else None,
                postgres_dsn=None,
                redis_url=None,
                langsmith_tracing=False,
            ),
            transport=httpx.MockTransport(upstream),
        )
    )
    return TestClient(app), calls


@pytest.mark.parametrize("key", [None, ""])
def test_no_key_explicit_check_and_read_never_dispatch(key, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy.invalid:9")
    client, calls = api(key)
    for response in [
        client.get("/api/v1/model-settings"),
        client.post("/api/v1/model-settings/check", headers={"X-Motif-Configuration-Check": "1"}),
    ]:
        assert response.json()["data"] == {"state": "not_configured", "error_code": None}
        assert response.headers["cache-control"] == "no-store"
    assert not calls


def test_environment_clear_does_not_rewrite_running_settings(monkeypatch):
    # Simulates launch-time state only, never reads a real Key or configuration file.
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    running, calls = api(KEY)
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert running.get("/api/v1/model-settings").json()["data"]["state"] == "configured"
    restarted, new_calls = api(None)
    assert restarted.get("/api/v1/model-settings").json()["data"]["state"] == "not_configured"
    assert not calls and not new_calls


def test_no_http_key_save_clear_or_enable_endpoint():
    client, calls = api()
    for method in ("put", "patch", "delete", "post"):
        response = getattr(client, method)("/api/v1/model-settings")
        assert response.status_code == 405
        assert KEY not in response.text
    assert not calls


def test_cross_site_with_configured_key_never_dispatches():
    client, calls = api(KEY)
    response = client.post(
        "/api/v1/model-settings/check",
        headers={"X-Motif-Configuration-Check": "1", "Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403 and KEY not in response.text
    assert not calls
