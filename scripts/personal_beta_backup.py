"""Backup plans/checks and an explicit maintenance-only creation entry.

Only create --execute can read a source DB and copy into a fresh backup target.
No command stops writers or restores a DB; restore remains a read-only plan.
Hash integrity alone cannot establish a DB/Artifact consistency point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath

MAX_FILES = 256
MAX_MEDIA_BYTES = 128 * 1024**2
MAX_DUMP_BYTES = 64 * 1024**2
MAX_MANIFEST_BYTES = 1024**2


class BackupCheckError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BackupCheckError(code)


def _root(path: Path) -> Path:
    _require(path.is_absolute() and ".." not in path.parts, "BACKUP_ROOT_INVALID")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise BackupCheckError("BACKUP_ROOT_UNAVAILABLE") from None
    _require(resolved == path and path.is_dir(), "BACKUP_ROOT_INVALID")
    return resolved


def _inside(path: Path, root: Path, *, exists: bool = True) -> Path:
    _require(path.is_absolute() and ".." not in path.parts, "BACKUP_PATH_INVALID")
    try:
        resolved = path.resolve(strict=exists)
    except (OSError, RuntimeError):
        raise BackupCheckError("BACKUP_PATH_UNAVAILABLE") from None
    _require(resolved == path, "BACKUP_PATH_SYMLINK")
    _require(root in path.parents, "BACKUP_PATH_OUTSIDE_ROOT")
    return path


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def _digest(path: Path, limit: int) -> tuple[int, str, bytes]:
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode), "BACKUP_FILE_NOT_REGULAR")
    _require(before.st_size <= limit, "BACKUP_FILE_BUDGET_EXCEEDED")
    checksum = hashlib.sha256()
    size = 0
    header = b""
    # Never follow a last-component link swapped in after lstat.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(
            stat.S_ISREG(opened.st_mode)
            and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            "BACKUP_FILE_CHANGED",
        )
        while chunk := stream.read(64 * 1024):
            if not header:
                header = chunk[:8]
            size += len(chunk)
            _require(size <= limit, "BACKUP_FILE_BUDGET_EXCEEDED")
            checksum.update(chunk)
        after = os.fstat(stream.fileno())
    _require(
        (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        and size == before.st_size,
        "BACKUP_FILE_CHANGED",
    )
    return size, checksum.hexdigest(), header


def _manifest(path: Path) -> dict:
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode), "BACKUP_MANIFEST_INVALID")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(
            stat.S_ISREG(opened.st_mode)
            and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            "BACKUP_FILE_CHANGED",
        )
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_MANIFEST_BYTES, "BACKUP_MANIFEST_BUDGET_EXCEEDED")
    _require(
        (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        and len(raw) == before.st_size,
        "BACKUP_FILE_CHANGED",
    )
    result = json.loads(raw)
    _require(isinstance(result, dict), "BACKUP_MANIFEST_INVALID")
    return result


def _row(row: dict) -> str:
    name = row["path"]
    _require(isinstance(name, str) and "\\" not in name, "BACKUP_MANIFEST_PATH_INVALID")
    relative = PurePosixPath(name)
    _require(
        not relative.is_absolute()
        and bool(relative.parts)
        and ".." not in relative.parts
        and relative.as_posix() == name,
        "BACKUP_MANIFEST_PATH_INVALID",
    )
    _require(type(row["bytes"]) is int and row["bytes"] > 0, "BACKUP_MANIFEST_INVALID")
    _require(
        isinstance(row["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
        "BACKUP_MANIFEST_INVALID",
    )
    return name


def _walk_error(_error):
    raise BackupCheckError("BACKUP_WALK_FAILED") from None


def _verified(backup: Path, allowed_root: Path) -> tuple[dict, dict]:
    root = _root(allowed_root)
    backup = _inside(backup, root)
    _require(backup.is_dir(), "BACKUP_DIRECTORY_INVALID")
    manifest_path = backup / "manifest.json"
    manifest = _manifest(manifest_path)
    _require(
        "schema_version" not in manifest
        or manifest["schema_version"] == "motif-beta-maintenance-backup.v1",
        "BACKUP_SCHEMA_UNSUPPORTED",
    )
    files = manifest["files"]
    metadata = manifest.get("platform_metadata", [])
    dump = manifest["db_dump"]
    _require(
        isinstance(files, list)
        and isinstance(metadata, list)
        and len(files) + len(metadata) <= MAX_FILES,
        "BACKUP_FILE_BUDGET_EXCEEDED",
    )
    expected = {"manifest.json"}
    payload_names = set()
    media_bytes = 0
    for row in files:
        name = _row(row)
        _require(name not in payload_names, "BACKUP_MANIFEST_DUPLICATE")
        payload_names.add(name)
        media_bytes += row["bytes"]
        _require(media_bytes <= MAX_MEDIA_BYTES, "BACKUP_MEDIA_BUDGET_EXCEEDED")
    for row in files + metadata:
        name = _row(row)
        key = "artifacts/" + name
        _require(key not in expected, "BACKUP_MANIFEST_DUPLICATE")
        expected.add(key)
        path = _inside(backup / key, root)
        is_metadata = row in metadata
        limit = min(row["bytes"], 1024**2 if is_metadata else MAX_MEDIA_BYTES)
        size, checksum, header = _digest(path, limit)
        _require((size, checksum) == (row["bytes"], row["sha256"]), "BACKUP_FILE_MISMATCH")
        if is_metadata:
            media_bytes += size
            _require(media_bytes <= MAX_MEDIA_BYTES, "BACKUP_MEDIA_BUDGET_EXCEEDED")
            relative = PurePosixPath(name)
            companion = relative.with_name(relative.name[2:])
            companion_path = backup / "artifacts" / companion
            _require(
                relative.name.startswith("._")
                and len(relative.name) > 2
                and 26 <= size <= 1024**2
                and header == bytes.fromhex("0005160700020000")
                and (companion.as_posix() in payload_names or companion_path.is_dir()),
                "BACKUP_METADATA_INVALID",
            )
    dump_name = _row(dump)
    _require(
        len(PurePosixPath(dump_name).parts) == 1 and dump_name != "manifest.json",
        "BACKUP_DUMP_PATH_INVALID",
    )
    expected.add(dump_name)
    size, checksum, _ = _digest(_inside(backup / dump_name, root), MAX_DUMP_BYTES)
    _require((size, checksum) == (dump["bytes"], dump["sha256"]), "BACKUP_DUMP_MISMATCH")
    actual = set()
    entries = 0
    for parent, directories, names in os.walk(backup, followlinks=False, onerror=_walk_error):
        entries += len(directories) + len(names)
        _require(entries <= MAX_FILES * 4, "BACKUP_FILE_BUDGET_EXCEEDED")
        for name in directories + names:
            path = Path(parent) / name
            _require(not path.is_symlink(), "BACKUP_PATH_SYMLINK")
            if not path.is_dir():
                _require(path.is_file(), "BACKUP_FILE_NOT_REGULAR")
                actual.add(path.relative_to(backup).as_posix())
                _require(len(actual) <= MAX_FILES + 2, "BACKUP_FILE_BUDGET_EXCEEDED")
    _require(actual == expected, "BACKUP_UNLISTED_OR_MISSING_FILES")
    return manifest, {
        "integrity": "verified",
        "artifact_files": len(files),
        "artifact_bytes": media_bytes,
        "platform_metadata_files": len(metadata),
        "dump_bytes": size,
        "db_artifact_consistency": "not_proven_by_integrity_check",
        "database_restore_tested": False,
    }


def verify_backup(backup: Path, allowed_root: Path) -> dict:
    if backup.is_file():
        if __package__:
            from .personal_beta_backup_archive import verify_archive
        else:
            from personal_beta_backup_archive import verify_archive
        return verify_archive(backup, allowed_root)
    return _verified(backup, allowed_root)[1]


def plan_backup(source: Path, destination: Path, allowed_root: Path) -> dict:
    root = _root(allowed_root)
    source = _inside(source, root)
    destination = _inside(destination, root, exists=False)
    _require(source.is_dir() and not destination.exists(), "BACKUP_TARGET_NOT_FRESH")
    _require(not _overlap(source, destination), "BACKUP_TARGET_OVERLAPS_SOURCE")
    return {
        "status": "backup_plan_only",
        "backup_performed": False,
        "required_evidence": [
            "all_writers_exited",
            "single_database_dump",
            "complete_artifact_inventory",
            "before_after_db_and_media_match",
            "isolated_restore_and_version_checks",
        ],
    }


def plan_restore(backup: Path, target: Path, allowed_root: Path) -> dict:
    if backup.is_file():
        if __package__:
            from .personal_beta_backup_archive import plan_restore_archive
        else:
            from personal_beta_backup_archive import plan_restore_archive
        return plan_restore_archive(backup, target, allowed_root)
    manifest, result = _verified(backup, allowed_root)
    target = _inside(target, _root(allowed_root), exists=False)
    source = Path(manifest["source_root"])
    _require(source.is_absolute() and ".." not in source.parts, "BACKUP_SOURCE_UNRECORDED")
    _require(not target.exists(), "BACKUP_TARGET_NOT_FRESH")
    _require(
        not _overlap(target, backup) and not _overlap(target, source),
        "BACKUP_TARGET_OVERLAPS_SOURCE",
    )
    return result | {
        "status": "restore_dry_run_only",
        "restore_performed": False,
        "ready_for_real_restore": False,
        "required_evidence": [
            "distinct_empty_database",
            "matching_schema_and_readers",
            "db_artifact_consistency",
            "isolated_restore_verified",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create", help="Default dry-run; --execute requires stopped writers"
    )
    create.add_argument("--contract", type=Path, required=True)
    create.add_argument("--execute", action="store_true")
    create.add_argument("--format", choices=("directory-v1", "archive-v2"), default="directory-v1")
    for name in ("plan", "verify", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--allowed-root", type=Path, required=True)
        if name == "plan":
            command.add_argument("--source", type=Path, required=True)
            command.add_argument("--destination", type=Path, required=True)
        else:
            command.add_argument("--backup", type=Path, required=True)
        if name == "restore":
            command.add_argument("--target", type=Path, required=True)
            command.add_argument("--dry-run", action="store_true", required=True)
    args = parser.parse_args(argv)
    controlled_errors = (BackupCheckError,)
    stage_error = ()
    try:
        if args.command == "create":
            if __package__:
                from .personal_beta_backup_create import create_backup, load_contract
                from .personal_beta_backup_failure import BackupStageError
                from .personal_beta_backup_runtime import BackupRuntimeError
            else:
                from personal_beta_backup_create import create_backup, load_contract
                from personal_beta_backup_failure import BackupStageError
                from personal_beta_backup_runtime import BackupRuntimeError
            controlled_errors += (BackupRuntimeError, BackupStageError)
            stage_error = (BackupStageError,)
            if args.format == "archive-v2":
                if __package__:
                    from .personal_beta_backup_archive_create import create_archive_backup
                else:
                    from personal_beta_backup_archive_create import create_archive_backup
                create_backup = create_archive_backup
            result = create_backup(load_contract(args.contract), execute=args.execute)
        elif args.command == "plan":
            result = plan_backup(args.source, args.destination, args.allowed_root)
        elif args.command == "verify":
            result = verify_backup(args.backup, args.allowed_root)
        else:
            result = plan_restore(args.backup, args.target, args.allowed_root)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        code = "BACKUP_INPUT_INVALID"
        if isinstance(exc, controlled_errors):
            code = (
                str(exc)
                if re.fullmatch(r"BACKUP_[A-Z0-9_]{1,64}", str(exc))
                else "BACKUP_RUNTIME_FAILED"
            )
        detail = {"error": code}
        if isinstance(exc, stage_error):
            detail["diagnostic"] = exc.diagnostic
        print(json.dumps(detail))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    # Sibling creation helpers must share the same controlled exception class
    # when this file is run directly rather than imported as scripts.*.
    sys.modules["personal_beta_backup"] = sys.modules[__name__]
    raise SystemExit(main())
