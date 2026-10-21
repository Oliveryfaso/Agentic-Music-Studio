"""Read-only resource and live capability gates for the local personal Beta."""

from __future__ import annotations

import argparse
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from resource_preflight import audit_resources

CONTRACT_PATH = Path(__file__).with_name("resource-contract.v1.json")
MAX_RESPONSE_BYTES = 256 * 1024
MESSAGES = {
    "BETA_HEALTH_URL_INVALID": (
        "实时检查地址必须为带端口的本机 HTTP 地址。API 与渲染地址须同时提供。"
    ),
    "BETA_HEALTH_UNAVAILABLE": "本机服务暂不可用。请检查本次启动的服务。",
    "BETA_HEALTH_RESPONSE_INVALID": "本机服务状态格式无效。请核对当前运行版本。",
    "BETA_PIANO_CAPABILITY_UNAVAILABLE": "API 尚未确认固定版本的审核钢琴包。",
    "BETA_SCORE_CATALOG_MISMATCH": "运行中的审核曲谱目录与固定契约不一致。",
    "BETA_RESOURCE_INPUT_INVALID": "资源契约或目录参数无效。请使用随项目提供的配置。",
}


class PreflightError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def local_origin(value):
    """Accept only an explicit 127.0.0.1 HTTP origin; never infer a remote URL."""
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
        if (
            parts.scheme != "http"
            or parts.hostname != "127.0.0.1"
            or port is None
            or not 1 <= port <= 65535
            or parts.netloc != f"127.0.0.1:{port}"
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError
        return f"http://127.0.0.1:{port}"
    except (ValueError, TypeError, AttributeError):
        raise PreflightError("BETA_HEALTH_URL_INVALID") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(newurl, code, "redirects disabled", headers, fp)


def read_json(url):
    """Make one bounded, proxy-free request without following redirects."""
    parts = urllib.parse.urlsplit(url)
    local_origin(urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", "")))
    if (
        parts.path not in {"/health", "/api/v1/piano-capability", "/api/v1/classical-scores"}
        or parts.query
        or parts.fragment
    ):
        raise PreflightError("BETA_HEALTH_URL_INVALID")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=2) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise PreflightError("BETA_HEALTH_RESPONSE_INVALID")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise PreflightError("BETA_HEALTH_RESPONSE_INVALID")
        return value
    except (ValueError, UnicodeError):
        raise PreflightError("BETA_HEALTH_RESPONSE_INVALID") from None
    except (OSError, urllib.error.URLError, http.client.HTTPException):
        raise PreflightError("BETA_HEALTH_UNAVAILABLE") from None


def check_resources(contract, repo, piano_root, *, api_url=None, render_url=None):
    requested = api_url is not None or render_url is not None
    result = {
        "schema_version": "motif-personal-beta-preflight.v1",
        "assets_verified": False,
        "resource_ready": False,
        "renderer_admission": "not_checked",
        "live_checks": "blocked" if requested else "not_requested",
        "issues": [],
    }
    try:
        if requested:
            if api_url is None or render_url is None:
                raise PreflightError("BETA_HEALTH_URL_INVALID")
            api_url, render_url = local_origin(api_url), local_origin(render_url)
        if not repo.is_absolute() or not piano_root.is_absolute():
            raise PreflightError("BETA_RESOURCE_INPUT_INVALID")
        scores = repo / "services/api/src/motif_forge/resources/scores"
        assets = audit_resources(contract, piano_root, scores)
        result["assets_verified"] = assets["assets_verified"]
        result["issues"].extend(assets["issues"])
        if not assets["assets_verified"] or not requested:
            return result
        health = read_json(render_url + "/health")
        admitted = audit_resources(contract, piano_root, scores, health)
        result["renderer_admission"] = admitted["renderer_admission"]
        result["issues"].extend(admitted["issues"])
        if not admitted["resource_ready"]:
            return result
        expected = contract["piano"]
        profile = {
            "instrument_pack_id": expected["pack_id"],
            "instrument_pack_version": expected["pack_version"],
            "manifest_sha256": expected["manifest_sha256"],
        }
        capability = read_json(api_url + "/api/v1/piano-capability").get("data")
        if (
            not isinstance(capability, dict)
            or capability.get("available") is not True
            or not isinstance(capability.get("render_profile"), dict)
            or any(capability["render_profile"].get(key) != value for key, value in profile.items())
        ):
            raise PreflightError("BETA_PIANO_CAPABILITY_UNAVAILABLE")
        catalog = read_json(api_url + "/api/v1/classical-scores").get("data")
        expected_ids = {item["score_id"] for item in contract["scores"]}
        if (
            not isinstance(catalog, list)
            or len(catalog) != len(expected_ids)
            or any(
                not isinstance(item, dict) or not isinstance(item.get("score_id"), str)
                for item in catalog
            )
            or {item.get("score_id") for item in catalog} != expected_ids
        ):
            raise PreflightError("BETA_SCORE_CATALOG_MISMATCH")
        result["resource_ready"] = True
        result["live_checks"] = "passed"
    except PreflightError as error:
        result["issues"].append({"code": error.code, "message_zh": MESSAGES[error.code]})
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        code = "BETA_RESOURCE_INPUT_INVALID"
        result["issues"].append({"code": code, "message_zh": MESSAGES[code]})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--piano-root", type=Path, required=True)
    parser.add_argument("--api-url")
    parser.add_argument("--render-url")
    args = parser.parse_args(argv)
    try:
        contract = json.loads(CONTRACT_PATH.read_text())
        result = check_resources(
            contract,
            args.repo,
            args.piano_root,
            api_url=args.api_url,
            render_url=args.render_url,
        )
    except (OSError, ValueError, TypeError, RuntimeError):
        code = "BETA_RESOURCE_INPUT_INVALID"
        result = {
            "schema_version": "motif-personal-beta-preflight.v1",
            "assets_verified": False,
            "resource_ready": False,
            "live_checks": "blocked",
            "issues": [{"code": code, "message_zh": MESSAGES[code]}],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    okay = result["assets_verified"] and result["live_checks"] in {"not_requested", "passed"}
    return 0 if okay else 2


if __name__ == "__main__":
    raise SystemExit(main())
