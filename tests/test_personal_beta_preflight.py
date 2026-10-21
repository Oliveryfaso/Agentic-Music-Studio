from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "scripts/personal_beta_preflight.py"


def load_gate():
    assert ENTRY.exists(), "personal Beta preflight entrypoint is missing"
    sys.path.insert(0, str(ENTRY.parent))
    spec = importlib.util.spec_from_file_location("personal_beta_gate", ENTRY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def digest(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    data = json.dumps(value, sort_keys=True).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest(data)


@pytest.fixture
def resources(tmp_path):
    repo = tmp_path / "repo"
    piano = tmp_path / "piano"
    scores = repo / "services/api/src/motif_forge/resources/scores"
    (piano / "samples").mkdir(parents=True)
    scores.mkdir(parents=True)
    sample, license_text = b"owned integrity bytes", b"owned license text"
    (piano / "samples/own.wav").write_bytes(sample)
    (piano / "cc0.txt").write_bytes(license_text)
    pin = write_json(
        piano / "instrument-pack.json",
        {
            "packId": "fixture:own",
            "packVersion": "test1",
            "license": {"spdx": "CC0-1.0", "textSha256": digest(license_text)},
            "samples": [
                {
                    "sampleId": "own",
                    "path": "samples/own.wav",
                    "sha256": digest(sample),
                    "byteSize": len(sample),
                }
            ],
        },
    )
    entries = []
    for index in range(4):
        score_id = f"fixture-{index}.v1"
        score_pin = write_json(
            scores / f"{index}.json", {"score_id": score_id, "license": "Public Domain"}
        )
        xml = f"owned score {index}".encode()
        (scores / f"{index}.xml").write_bytes(xml)
        entries.append(
            {
                "score_id": score_id,
                "title": "自制测试谱",
                "manifest_path": f"{index}.json",
                "manifest_sha256": score_pin,
                "license": "Public Domain",
                "files": [{"path": f"{index}.xml", "sha256": digest(xml)}],
            }
        )
    contract = {
        "schema_version": "motif-resource-contract.v1",
        "piano": {
            "pack_id": "fixture:own",
            "pack_version": "test1",
            "manifest_sha256": pin,
            "license_sha256": digest(license_text),
            "sample_count": 1,
        },
        "scores": entries,
    }
    return repo, piano, contract


def replies(contract):
    piano = contract["piano"]
    return {
        "http://127.0.0.1:18090/health": {
            "status": "ready",
            "instrumentPacks": [
                {
                    "packId": piano["pack_id"],
                    "packVersion": piano["pack_version"],
                    "manifestSha256": piano["manifest_sha256"],
                }
            ],
        },
        "http://127.0.0.1:18000/api/v1/piano-capability": {
            "data": {
                "available": True,
                "render_profile": {
                    "instrument_pack_id": piano["pack_id"],
                    "instrument_pack_version": piano["pack_version"],
                    "manifest_sha256": piano["manifest_sha256"],
                },
            }
        },
        "http://127.0.0.1:18000/api/v1/classical-scores": {
            "data": [{"score_id": item["score_id"]} for item in contract["scores"]]
        },
    }


def run_check(gate, resources, monkeypatch, values=None, **kwargs):
    repo, piano, contract = resources
    calls = []

    def fetch(url):
        calls.append(url)
        return (values or replies(contract))[url]

    monkeypatch.setattr(gate, "read_json", fetch)
    result = gate.check_resources(contract, repo, piano, **kwargs)
    return result, calls


def live_urls():
    return {"api_url": "http://127.0.0.1:18000", "render_url": "http://127.0.0.1:18090"}


def test_offline_assets_do_not_make_live_readiness(resources, monkeypatch):
    result, calls = run_check(load_gate(), resources, monkeypatch)
    assert result["assets_verified"] is True
    assert result["resource_ready"] is False
    assert result["live_checks"] == "not_requested" and not calls


def test_bad_assets_stop_before_http(resources, monkeypatch):
    (resources[1] / "samples/own.wav").write_bytes(b"bad")
    result, calls = run_check(load_gate(), resources, monkeypatch, **live_urls())
    assert not result["assets_verified"] and not result["resource_ready"] and not calls


def test_live_checks_require_renderer_api_and_four_scores(resources, monkeypatch):
    result, calls = run_check(load_gate(), resources, monkeypatch, **live_urls())
    assert result["resource_ready"] is True and result["live_checks"] == "passed"
    assert len(calls) == 3 and not result["issues"]


def test_plain_renderer_ready_is_not_admission(resources, monkeypatch):
    values = replies(resources[2])
    values["http://127.0.0.1:18090/health"] = {"status": "ready"}
    result, calls = run_check(load_gate(), resources, monkeypatch, values, **live_urls())
    assert not result["resource_ready"] and len(calls) == 1
    assert "RENDERER_PACK_NOT_ADMITTED" in {item["code"] for item in result["issues"]}


@pytest.mark.parametrize("failure", ["unavailable", "wrong-pin", "truthy-string"])
def test_capability_must_be_true_and_match_pin(resources, monkeypatch, failure):
    values = replies(resources[2])
    capability = values["http://127.0.0.1:18000/api/v1/piano-capability"]["data"]
    if failure == "wrong-pin":
        capability["render_profile"]["manifest_sha256"] = "0" * 64
    else:
        capability["available"] = "true" if failure == "truthy-string" else False
    result, calls = run_check(load_gate(), resources, monkeypatch, values, **live_urls())
    assert not result["resource_ready"] and len(calls) == 2
    assert result["issues"][-1]["code"] == "BETA_PIANO_CAPABILITY_UNAVAILABLE"


@pytest.mark.parametrize("failure", ["missing", "duplicate", "wrong-id", "malformed-id"])
def test_catalog_must_match_contract_exactly(resources, monkeypatch, failure):
    values = replies(resources[2])
    catalog = values["http://127.0.0.1:18000/api/v1/classical-scores"]["data"]
    if failure == "missing":
        catalog.pop()
    elif failure == "duplicate":
        catalog[-1] = catalog[0]
    elif failure == "wrong-id":
        catalog[-1] = {"score_id": "unknown"}
    else:
        catalog[-1] = {"score_id": []}
    result, calls = run_check(load_gate(), resources, monkeypatch, values, **live_urls())
    assert not result["resource_ready"] and len(calls) == 3
    assert result["issues"][-1]["code"] == "BETA_SCORE_CATALOG_MISMATCH"


@pytest.mark.parametrize(
    "api_url,render_url",
    [
        ("http://example.com:18000", "http://127.0.0.1:18090"),
        ("http://127.0.0.1:18000/private", "http://127.0.0.1:18090"),
        ("http://user:secret@127.0.0.1:18000", "http://127.0.0.1:18090"),
        ("http://127.0.0.1:0", "http://127.0.0.1:18090"),
        ("https://127.0.0.1:18000", "http://127.0.0.1:18090"),
        ("http://127.0.0.1:18000", None),
    ],
)
def test_nonlocal_or_incomplete_urls_fail_without_http(resources, monkeypatch, api_url, render_url):
    result, calls = run_check(
        load_gate(), resources, monkeypatch, api_url=api_url, render_url=render_url
    )
    assert not result["resource_ready"] and not calls
    assert result["issues"][-1]["code"] == "BETA_HEALTH_URL_INVALID"
    assert "secret" not in json.dumps(result)


def test_read_json_disables_proxy_redirects_and_bounds_io(monkeypatch):
    gate = load_gate()
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            seen["limit"] = limit
            return b'{"status":"ready"}'

    class Opener:
        def open(self, request, timeout):
            seen["url"], seen["timeout"] = request.full_url, timeout
            return Response()

    def build(*handlers):
        seen["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(gate.urllib.request, "build_opener", build)
    assert gate.read_json("http://127.0.0.1:18090/health") == {"status": "ready"}
    assert seen["timeout"] == 2 and seen["limit"] == 262145
    proxy = next(h for h in seen["handlers"] if hasattr(h, "proxies"))
    assert proxy.proxies == {}
    redirect = next(h for h in seen["handlers"] if hasattr(h, "redirect_request"))
    with pytest.raises(urllib.error.HTTPError):
        redirect.redirect_request(None, None, 302, "redirect", {}, "http://example.com/")


@pytest.mark.parametrize(
    "body", [b"not-json", b"x" * 262145, b"[]"], ids=["invalid-json", "oversized", "not-object"]
)
def test_read_json_rejects_invalid_or_oversized_response(monkeypatch, body):
    gate = load_gate()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return body[:limit]

    class Opener:
        def open(self, request, timeout):
            return Response()

    monkeypatch.setattr(gate.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(gate.PreflightError, match="BETA_HEALTH_RESPONSE_INVALID"):
        gate.read_json("http://127.0.0.1:18090/health")


def test_transport_failure_is_safe_and_terminal(resources, monkeypatch):
    gate = load_gate()

    def fail(url):
        raise gate.PreflightError("BETA_HEALTH_UNAVAILABLE")

    monkeypatch.setattr(gate, "read_json", fail)
    result = gate.check_resources(resources[2], *resources[:2], **live_urls())
    assert not result["resource_ready"]
    assert result["issues"][-1]["code"] == "BETA_HEALTH_UNAVAILABLE"


def test_cli_offline_success_and_live_failure_exit_codes(resources, monkeypatch, capsys):
    gate = load_gate()
    repo, piano, contract = resources
    contract_path = repo / "contract.json"
    write_json(contract_path, contract)
    monkeypatch.setattr(gate, "CONTRACT_PATH", contract_path)
    assert gate.main(["--repo", str(repo), "--piano-root", str(piano)]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["assets_verified"] and not value["resource_ready"]
    assert gate.main(["--repo", str(repo), "--piano-root", str(piano / "missing")]) == 2
    value = json.loads(capsys.readouterr().out)
    assert not value["assets_verified"] and str(repo) not in json.dumps(value)
