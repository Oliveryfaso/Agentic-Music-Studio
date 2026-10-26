import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from motif_forge.api.model_settings import build_model_settings_router
from motif_forge.config import Settings
from pydantic import SecretStr

KEY = "sk-mock-settings-only-0123456789"


def client(configured=True, handler=None):
    settings = Settings.for_test(
        deepseek_api_key=SecretStr(KEY) if configured else None,
        postgres_dsn=None,
        redis_url=None,
        langsmith_tracing=False,
    )
    app = FastAPI()
    app.include_router(
        build_model_settings_router(
            settings,
            transport=httpx.MockTransport(handler) if handler else None,
        )
    )
    return TestClient(app)


def test_read_local_configuration_never_calls_remote():
    def remote(_):
        pytest.fail("reading configuration must not send remote traffic")

    for configured, expected in [(False, "not_configured"), (True, "configured")]:
        response = client(configured, remote).get("/api/v1/model-settings")
        assert response.json()["data"]["state"] == expected
        assert response.headers["cache-control"] == "no-store"
        assert KEY not in response.text


def test_explicit_check_uses_only_fixed_models_endpoint_and_no_music():
    requests = []

    def remote(request):
        requests.append(request)
        assert str(request.url) == "https://api.deepseek.com/models"
        assert request.method == "GET" and not request.content
        assert request.headers["authorization"] == "Bearer " + KEY
        return httpx.Response(200, json={"object": "list", "data": [{"id": "model"}]})

    api = client(handler=remote)
    assert api.post("/api/v1/model-settings/check").status_code == 403
    response = api.post(
        "/api/v1/model-settings/check", headers={"X-Motif-Configuration-Check": "1"}
    )
    assert response.json()["data"]["state"] == "connected"
    assert len(requests) == 1 and KEY not in response.text
    assert api.get("/api/v1/model-settings").json()["data"]["state"] == "configured"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTHENTICATION_FAILED"),
        (403, "AUTHENTICATION_FAILED"),
        (429, "PROVIDER_UNAVAILABLE"),
        (302, "PROVIDER_UNAVAILABLE"),
        (500, "PROVIDER_UNAVAILABLE"),
    ],
)
def test_remote_error_is_sanitized_without_retries(status, code):
    count = 0

    def remote(_):
        nonlocal count
        count += 1
        return httpx.Response(status, text=KEY, headers={"Location": "https://untrusted.invalid"})

    response = client(handler=remote).post(
        "/api/v1/model-settings/check", headers={"X-Motif-Configuration-Check": "1"}
    )
    assert response.json()["data"] == {"state": "failed", "error_code": code}
    assert KEY not in response.text and count == 1


def test_not_configured_and_cross_site_checks_do_not_call_remote():
    def remote(_):
        pytest.fail("must not call remote")

    api = client(False, remote)
    assert (
        api.post(
            "/api/v1/model-settings/check", headers={"X-Motif-Configuration-Check": "1"}
        ).json()["data"]["state"]
        == "not_configured"
    )
    assert (
        api.post(
            "/api/v1/model-settings/check",
            headers={"X-Motif-Configuration-Check": "1", "Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )


def test_timeout_and_invalid_response_are_sanitized():
    def timeout(request):
        raise httpx.ReadTimeout(KEY, request=request)

    for handler, code in [
        (timeout, "CONNECTION_FAILED"),
        (lambda _: httpx.Response(200, json={"secret": KEY}), "INVALID_RESPONSE"),
    ]:
        response = client(handler=handler).post(
            "/api/v1/model-settings/check", headers={"X-Motif-Configuration-Check": "1"}
        )
        assert response.json()["data"] == {"state": "failed", "error_code": code}
        assert KEY not in response.text


def test_app_wires_configuration_read_without_persistence_or_secrets():
    from motif_forge.api.app import create_app

    settings = Settings.for_test(
        deepseek_api_key=SecretStr(KEY),
        postgres_dsn=None,
        redis_url=None,
        langsmith_tracing=False,
    )
    response = TestClient(create_app(settings)).get("/api/v1/model-settings")
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "configured"
    assert KEY not in response.text


def test_check_does_not_send_key_to_custom_endpoint():
    def remote(_):
        pytest.fail("must not forward a Secret to custom endpoints")

    settings = Settings.for_test(
        deepseek_api_key=SecretStr(KEY),
        deepseek_base_url="https://untrusted.invalid",
        postgres_dsn=None,
        redis_url=None,
        langsmith_tracing=False,
    )
    app = FastAPI()
    app.include_router(build_model_settings_router(settings, transport=httpx.MockTransport(remote)))
    response = TestClient(app).post(
        "/api/v1/model-settings/check",
        headers={"X-Motif-Configuration-Check": "1"},
    )
    assert response.json()["data"] == {"state": "failed", "error_code": "ENDPOINT_UNSUPPORTED"}
    assert KEY not in response.text
