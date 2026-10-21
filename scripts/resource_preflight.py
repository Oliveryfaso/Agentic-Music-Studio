#!/usr/bin/env python3
"""Offline, read-only integrity preflight for an explicitly reviewed resource contract.

No downloads, repairs, license acceptance, permissions, subprocesses or audio decode.
Production loadReviewedInstrumentCatalog remains the PCM/schema admission authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MESSAGES = {
    "PIANO_CONFIGURATION_MISSING": ("钢琴资源未配置", "请配置已审核钢琴包的目录与固定版本。"),
    "PIANO_ROOT_UNAVAILABLE": ("钢琴资源目录不可用", "请检查资源盘和只读挂载。恢复原审核目录。"),
    "SCORE_ROOT_UNAVAILABLE": ("审核谱库目录不可用", "请恢复与当前程序版本配套的内置谱库。"),
    "RESOURCE_FILE_MISSING": ("资源文件缺失", "请恢复同一审核版本的完整资源后重新检查。"),
    "RESOURCE_FILE_UNREADABLE": (
        "资源文件无法读取",
        "请检查运行环境的读取条件。本工具不会修改权限。",
    ),
    "RESOURCE_FILE_UNSAFE": (
        "资源文件路径不符合要求",
        "请使用审核包中的原文件。勿用符号链接替代。",
    ),
    "RESOURCE_MANIFEST_HASH_MISMATCH": (
        "资源清单与审核版本不符",
        "请恢复固定版本。勿用新哈希跳过检查。",
    ),
    "RESOURCE_LICENSE_HASH_MISMATCH": (
        "资源许可文件与审核版本不符",
        "请恢复该版本随附的许可文件。",
    ),
    "RESOURCE_HASH_MISMATCH": ("资源文件校验失败", "请恢复同一审核版本的原文件。"),
    "RESOURCE_SIZE_MISMATCH": ("资源文件大小不符", "请恢复同一审核版本的完整文件。"),
    "RESOURCE_MANIFEST_INVALID": ("资源清单内容不符合要求", "请恢复已经审核的资源清单。"),
    "RESOURCE_LICENSE_NOT_APPROVED": (
        "资源不在当前许可范围内",
        "请使用已审核资源。本工具不会接受新许可。",
    ),
    "RESOURCE_IDENTITY_MISMATCH": ("资源身份与固定版本不符", "请恢复与程序一致的审核资源。"),
    "RENDERER_NOT_READY": ("钢琴播放服务尚未就绪", "请在服务就绪后重新检查资源状态。"),
    "RENDERER_PACK_NOT_ADMITTED": (
        "钢琴包尚未载入播放服务",
        "请检查播放服务的资源挂载和固定版本配置。",
    ),
}


class ResourceError(Exception):
    def __init__(self, code, relative_path=None):
        self.code, self.relative_path = code, relative_path
        super().__init__(code)


def _root(value, code):
    try:
        root = Path(value).resolve(strict=True)
        if not root.is_dir():
            raise ResourceError(code)
        return root
    except (OSError, TypeError, RuntimeError):
        raise ResourceError(code) from None


def _read(root, relative, pin, maximum=128_000, size=None, mismatch="RESOURCE_HASH_MISMATCH"):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ResourceError("RESOURCE_FILE_UNSAFE")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or str(parts) != relative or any(p in ("..", ".") for p in parts.parts):
        raise ResourceError("RESOURCE_FILE_UNSAFE", relative)
    if not isinstance(pin, str) or not re.fullmatch("[a-f0-9]{64}", pin):
        raise ResourceError("RESOURCE_MANIFEST_INVALID", relative)
    path = root.joinpath(*parts.parts)
    try:
        if path.resolve(strict=True) != path or not stat.S_ISREG(path.lstat().st_mode):
            raise ResourceError("RESOURCE_FILE_UNSAFE", relative)
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise ResourceError("RESOURCE_FILE_UNSAFE", relative)
            if size is not None and info.st_size != size:
                raise ResourceError("RESOURCE_SIZE_MISMATCH", relative)
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(maximum + 1)
        finally:
            os.close(fd)
    except FileNotFoundError:
        raise ResourceError("RESOURCE_FILE_MISSING", relative) from None
    except PermissionError:
        raise ResourceError("RESOURCE_FILE_UNREADABLE", relative) from None
    except (OSError, RuntimeError):
        raise ResourceError("RESOURCE_FILE_UNSAFE", relative) from None
    if len(data) > maximum:
        raise ResourceError("RESOURCE_FILE_UNSAFE", relative)
    if hashlib.sha256(data).hexdigest() != pin:
        raise ResourceError(mismatch, relative)
    return data


def _manifest(root, relative, pin):
    try:
        value = json.loads(_read(root, relative, pin, mismatch="RESOURCE_MANIFEST_HASH_MISMATCH"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise ResourceError("RESOURCE_MANIFEST_INVALID", relative) from None


def audit_resources(contract, piano_root, scores_root, renderer_health=None):
    issues = []

    def record(resource, error):
        message, action = MESSAGES.get(error.code, MESSAGES["RESOURCE_MANIFEST_INVALID"])
        issues.append(
            {
                "resource": resource,
                "code": error.code,
                "relative_path": error.relative_path,
                "message_zh": message,
                "action_zh": action,
            }
        )

    expected = contract["piano"]
    piano = {
        "status": "unchecked",
        "pack_id": expected["pack_id"],
        "pack_version": expected["pack_version"],
        "manifest_sha256": expected["manifest_sha256"],
        "license_id": "CC0-1.0",
        "verified_sample_count": 0,
    }
    try:
        if not piano_root:
            raise ResourceError("PIANO_CONFIGURATION_MISSING")
        root = _root(piano_root, "PIANO_ROOT_UNAVAILABLE")
        manifest = _manifest(root, "instrument-pack.json", expected["manifest_sha256"])
        if (manifest.get("packId"), manifest.get("packVersion")) != (
            expected["pack_id"],
            expected["pack_version"],
        ):
            raise ResourceError("RESOURCE_IDENTITY_MISMATCH", "instrument-pack.json")
        license_info = manifest.get("license", {})
        if (
            license_info.get("spdx") != "CC0-1.0"
            or license_info.get("textSha256") != expected["license_sha256"]
        ):
            raise ResourceError("RESOURCE_LICENSE_NOT_APPROVED", "instrument-pack.json")
        _read(
            root,
            "cc0.txt",
            expected["license_sha256"],
            32 * 1024,
            mismatch="RESOURCE_LICENSE_HASH_MISMATCH",
        )
        samples = manifest.get("samples")
        if (
            not isinstance(samples, list)
            or len(samples) != expected["sample_count"]
            or not 1 <= len(samples) <= 64
        ):
            raise ResourceError("RESOURCE_MANIFEST_INVALID", "instrument-pack.json")
        for sample in samples:
            _read(root, sample["path"], sample["sha256"], 4 * 1024**2, size=sample["byteSize"])
            piano["verified_sample_count"] += 1
        for notice in expected.get("notice_files", []):
            _read(root, notice["path"], notice["sha256"], 32 * 1024)
        piano["status"] = "verified"
    except ResourceError as error:
        piano["status"] = "blocked"
        record("piano", error)
    except (KeyError, TypeError):
        piano["status"] = "blocked"
        record("piano", ResourceError("RESOURCE_MANIFEST_INVALID", "instrument-pack.json"))

    scores = {
        "status": "unchecked",
        "expected_count": len(contract["scores"]),
        "verified_count": 0,
        "items": [],
    }
    try:
        root = _root(scores_root, "SCORE_ROOT_UNAVAILABLE")
        for entry in contract["scores"]:
            item = {
                "score_id": entry["score_id"],
                "title": entry["title"],
                "status": "unchecked",
                "simplified": entry.get("simplified", True),
                "simplification_summary": entry.get("simplification_summary", ""),
            }
            try:
                manifest = _manifest(root, entry["manifest_path"], entry["manifest_sha256"])
                if manifest.get("score_id") != entry["score_id"]:
                    raise ResourceError("RESOURCE_IDENTITY_MISMATCH", entry["manifest_path"])
                if (
                    manifest.get("license") != "Public Domain"
                    or entry["license"] != "Public Domain"
                ):
                    raise ResourceError("RESOURCE_LICENSE_NOT_APPROVED", entry["manifest_path"])
                if not 1 <= len(entry["files"]) <= 32:
                    raise ResourceError("RESOURCE_MANIFEST_INVALID", entry["manifest_path"])
                for file in entry["files"]:
                    _read(root, file["path"], file["sha256"])
                item["status"] = "verified"
                scores["verified_count"] += 1
            except ResourceError as error:
                item["status"] = "blocked"
                record(entry["score_id"], error)
            scores["items"].append(item)
        scores["status"] = (
            "verified" if scores["verified_count"] == scores["expected_count"] else "blocked"
        )
    except ResourceError as error:
        scores["status"] = "blocked"
        record("scores", error)
    except (KeyError, TypeError):
        scores["status"] = "blocked"
        record("scores", ResourceError("RESOURCE_MANIFEST_INVALID"))

    admitted = "not_checked"
    if renderer_health is not None:
        admitted = "mismatch"
        identity = {
            "packId": expected["pack_id"],
            "packVersion": expected["pack_version"],
            "manifestSha256": expected["manifest_sha256"],
        }
        if not isinstance(renderer_health, dict) or renderer_health.get("status") != "ready":
            record("renderer", ResourceError("RENDERER_NOT_READY"))
        elif (
            not isinstance(renderer_health.get("instrumentPacks"), list)
            or identity not in renderer_health["instrumentPacks"]
        ):
            record("renderer", ResourceError("RENDERER_PACK_NOT_ADMITTED"))
        else:
            admitted = "matched"
    assets_verified = piano["status"] == scores["status"] == "verified"
    ready = assets_verified and admitted == "matched"
    return {
        "schema_version": "motif-resource-preflight.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - standalone Python 3.9 CLI
        "scope": "offline_files_and_optional_health_snapshot",
        "status": "ready_as_reported" if ready else "blocked" if issues else "assets_verified",
        "assets_verified": assets_verified,
        "resource_ready": ready,
        "renderer_admission": admitted,
        "renderer_evidence": "provided_health_snapshot" if renderer_health is not None else "none",
        "piano": piano,
        "scores": scores,
        "issues": issues,
        "limitations": [
            "No audio decoding or playback; runtime PCM validation remains in the existing loader.",
            (
                "No Compose/DB/API verification; a supplied health snapshot "
                "is not proof of a fresh live service."
            ),
            "No license approval, repair, download or permission change is performed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--piano-root", type=Path)
    parser.add_argument(
        "--renderer-health",
        type=Path,
        help="Optional health JSON captured by the mainline; this tool makes no network calls.",
    )
    args = parser.parse_args()
    try:
        contract = json.loads(Path(__file__).with_name("resource-contract.v1.json").read_text())
        health = json.loads(args.renderer_health.read_text()) if args.renderer_health else None
        result = audit_resources(
            contract,
            args.piano_root or os.environ.get("MOTIF_FORGE_REVIEWED_PIANO_ROOT"),
            args.repo / "services/api/src/motif_forge/resources/scores",
            health,
        )
    except (OSError, ValueError, KeyError, TypeError):
        result = {
            "schema_version": "motif-resource-preflight.v1",
            "status": "blocked",
            "assets_verified": False,
            "resource_ready": False,
            "issues": [
                {
                    "code": "RESOURCE_INPUT_INVALID",
                    "message_zh": "预检契约或状态文件不可用",
                    "action_zh": "请使用配套的预检契约与有效状态文件。",
                }
            ],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
