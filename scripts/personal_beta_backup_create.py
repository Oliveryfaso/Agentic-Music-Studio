"""Explicit, cooperative-maintenance backup creation; never stops a service.

The default is a path/contract plan. Only execute=True reads application data.
Independent application restore and power-loss durability remain separate gates.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import UUID

if __package__:
    from . import personal_beta_backup as checks
    from .personal_beta_backup_failure import attach_cleanup, make_failure
else:
    import personal_beta_backup as checks
    from personal_beta_backup_failure import attach_cleanup, make_failure

SERVICES = frozenset(
    (
        "api",
        "dispatcher",
        "resume-dispatcher",
        "media-worker",
        "render-worker",
        "migrate",
        "storage-init",
        "postgres",
        "redis",
    )
)
REVISION = "20261020_0030"
FIELDS = frozenset(
    (
        "schema",
        "allowed_root",
        "source",
        "destination",
        "runtime_dir",
        "project_root",
        "compose_project",
        "daemon_id",
        "owner",
        "containers",
        "images",
        "expected_db_revision",
    )
)


def require(condition, code):
    if not condition:
        raise checks.BackupCheckError(code)


def validate_contract(contract):
    require(isinstance(contract, dict) and set(contract) == FIELDS, "BACKUP_CONTRACT_INVALID")
    require(
        contract["schema"] == "motif-beta-backup-create.v1"
        and contract["expected_db_revision"] == REVISION,
        "BACKUP_SCHEMA_UNSUPPORTED",
    )
    require(
        isinstance(contract["owner"], str) and str(UUID(contract["owner"])) == contract["owner"],
        "BACKUP_OWNER_INVALID",
    )
    require(
        isinstance(contract["daemon_id"], str) and 0 < len(contract["daemon_id"]) <= 80,
        "BACKUP_DAEMON_INVALID",
    )
    require(
        isinstance(contract["compose_project"], str)
        and re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", contract["compose_project"]),
        "BACKUP_PROJECT_INVALID",
    )
    for key, pattern in (("containers", r"[0-9a-f]{64}"), ("images", r"sha256:[0-9a-f]{64}")):
        values = contract[key]
        require(
            isinstance(values, dict)
            and set(values) == SERVICES
            and all(isinstance(v, str) and re.fullmatch(pattern, v) for v in values.values()),
            "BACKUP_CONTAINER_IDENTITY_INVALID",
        )
    require(
        len(set(contract["containers"].values())) == len(SERVICES), "BACKUP_DUPLICATE_CONTAINER"
    )
    root = checks._root(Path(contract["allowed_root"]))
    source, target = Path(contract["source"]), Path(contract["destination"])
    checks.plan_backup(source, target, root)
    require(target.parent.is_dir(), "BACKUP_TARGET_PARENT_MISSING")
    checks._root(Path(contract["project_root"]))
    checks._root(Path(contract["runtime_dir"]))
    return root, source, target


def load_contract(path):
    require(path.is_absolute() and path.resolve() == path, "BACKUP_CONTRACT_PATH_INVALID")
    result = checks._manifest(path)
    validate_contract(result)
    return result


def _private_file(path):
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1,
        "BACKUP_RUNTIME_METADATA_INVALID",
    )
    return info


@contextmanager
def maintenance_lock(contract):
    runtime = Path(contract["runtime_dir"])
    info = runtime.stat()
    require(
        info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
        "BACKUP_RUNTIME_NOT_PRIVATE",
    )
    _private_file(runtime / "stack.json")
    record = checks._manifest(runtime / "stack.json")
    require(
        record.get("schema") == "motif-owned-stack.v1"
        and all(
            record.get(key) == contract[key]
            for key in ("project_root", "compose_project", "daemon_id", "owner")
        ),
        "BACKUP_RUNTIME_IDENTITY_MISMATCH",
    )
    lock_path = runtime / "operation.lock"
    named = _private_file(lock_path)
    with os.fdopen(os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK), "r+b") as lock:
        held = os.fstat(lock.fileno())
        require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino), "BACKUP_LOCK_CHANGED")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise checks.BackupCheckError("BACKUP_RUNTIME_BUSY") from None
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def inventory(source):
    rows, metadata, total, entries = [], [], 0, 0
    for parent, directories, names in os.walk(
        source, followlinks=False, onerror=checks._walk_error
    ):
        entries += len(directories) + len(names)
        require(entries <= checks.MAX_FILES * 4, "BACKUP_FILE_BUDGET_EXCEEDED")
        for name in directories:
            require(not (Path(parent) / name).is_symlink(), "BACKUP_PATH_SYMLINK")
        for name in sorted(names):
            path = checks._inside(Path(parent) / name, source)
            relative = path.relative_to(source).as_posix()
            size, digest, header = checks._digest(path, checks.MAX_MEDIA_BYTES)
            total += size
            require(
                total <= checks.MAX_MEDIA_BYTES and len(rows) + len(metadata) < checks.MAX_FILES,
                "BACKUP_FILE_BUDGET_EXCEEDED",
            )
            row = {"path": relative, "bytes": size, "sha256": digest}
            checks._row(row)
            if name.startswith("._"):
                require(
                    len(name) > 2
                    and header == bytes.fromhex("0005160700020000")
                    and 26 <= size <= 1024**2
                    and (Path(parent) / name[2:]).exists(),
                    "BACKUP_METADATA_INVALID",
                )
                checks._inside(Path(parent) / name[2:], source)
                metadata.append(row)
            else:
                rows.append(row)
    return {
        "files": sorted(rows, key=lambda x: x["path"]),
        "platform_metadata": sorted(metadata, key=lambda x: x["path"]),
    }


def copy_row(source, destination, row):
    relative = PurePosixPath(row["path"])
    target = destination.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    path = checks._inside(source.joinpath(*relative.parts), source)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as inp:
        require(stat.S_ISREG(os.fstat(inp.fileno()).st_mode), "BACKUP_FILE_NOT_REGULAR")
        with target.open("xb") as out:
            remaining, digest = row["bytes"], hashlib.sha256()
            while chunk := inp.read(min(64 * 1024, remaining + 1)):
                require(len(chunk) <= remaining, "BACKUP_FILE_CHANGED")
                out.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            require(remaining == 0 and digest.hexdigest() == row["sha256"], "BACKUP_FILE_CHANGED")
            out.flush()
            os.fsync(out.fileno())


def create_backup(contract, *, execute=False, factory=None):
    state = {"stage": "contract", "key": None, "first": None}
    try:
        return _create_backup(contract, execute=execute, factory=factory, state=state)
    except (Exception, KeyboardInterrupt) as error:
        first = state["first"]
        if first is not None and error is not first:
            raise attach_cleanup(first, error) from None
        raise make_failure(state["stage"], error, state["key"]) from None


def _create_backup(contract, *, execute, factory, state):
    root, source, target = validate_contract(contract)
    if not execute:
        return checks.plan_backup(source, target, root) | {
            "execution_requires_maintenance": True,
            "supported_schema": REVISION,
        }
    state["stage"] = "maintenance_lock"
    with maintenance_lock(contract):
        if factory is None:
            if __package__:
                from .personal_beta_backup_runtime import DockerBackupRuntime
            else:
                from personal_beta_backup_runtime import DockerBackupRuntime
            factory = DockerBackupRuntime
        runtime = factory(contract)
        try:
            state["stage"] = "writer_quiescence"
            runtime.assert_quiescent()
            state["stage"] = "inventory_before"
            source_identity = (source.stat().st_dev, source.stat().st_ino)
            before = inventory(source)
            state["stage"] = "database_snapshot_before"
            db_before = runtime.snapshot()
            require(
                db_before.get("database") == "motif_forge"
                and db_before.get("schema_revision") == REVISION,
                "BACKUP_DATABASE_MISMATCH",
            )
            required = (
                sum(x["bytes"] for x in before["files"] + before["platform_metadata"])
                + checks.MAX_DUMP_BYTES
            )
            space = os.statvfs(target.parent)
            require(
                space.f_bavail * space.f_frsize >= required + 1024**2,
                "BACKUP_TARGET_SPACE_INSUFFICIENT",
            )
            state["stage"] = "target_create"
            target.mkdir(mode=0o700)
            dump = target / "beta.pgdump"
            state["stage"] = "dump_write"
            with os.fdopen(os.open(dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
                runtime.dump(out, checks.MAX_DUMP_BYTES)
                out.flush()
                os.fsync(out.fileno())
            dump_bytes, dump_hash, header = checks._digest(dump, checks.MAX_DUMP_BYTES)
            require(dump_bytes > 5 and header.startswith(b"PGDMP"), "BACKUP_DUMP_INVALID")
            artifacts = target / "artifacts"
            artifacts.mkdir(mode=0o700)
            for row in before["files"] + before["platform_metadata"]:
                state.update(stage="artifact_copy", key=row["path"])
                copy_row(source, artifacts, row)
            for row in before["platform_metadata"]:
                companion = PurePosixPath(row["path"])
                companion = companion.with_name(companion.name[2:])
                if source.joinpath(*companion.parts).is_dir():
                    artifacts.joinpath(*companion.parts).mkdir(parents=True, exist_ok=True)
            state.update(stage="inventory_after", key=None)
            require(
                inventory(source) == before
                and (source.stat().st_dev, source.stat().st_ino) == source_identity,
                "BACKUP_SOURCE_CHANGED",
            )
            state["stage"] = "database_snapshot_after"
            require(runtime.snapshot() == db_before, "BACKUP_DATABASE_CHANGED")
            state["stage"] = "writer_quiescence"
            runtime.assert_quiescent()
            state["stage"] = "inventory_after"
            require(inventory(artifacts) == before, "BACKUP_COPY_MISMATCH")
            manifest = {
                "schema_version": "motif-beta-maintenance-backup.v1",
                "source_root": str(source),
                **before,
                "db_dump": {"path": "beta.pgdump", "bytes": dump_bytes, "sha256": dump_hash},
                "db_tables": db_before["tables"],
                "db_sequences": db_before["sequences"],
                "schema_revision": REVISION,
                "source_identity": {
                    k: contract[k]
                    for k in ("daemon_id", "compose_project", "owner", "containers", "images")
                },
                "consistency_boundary": "cooperative_single_host_maintenance",
                "database_restore_tested": False,
            }
            state["stage"] = "archive_manifest"
            with (target / "manifest.json").open("x") as out:
                json.dump(manifest, out, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
            state["stage"] = "archive_verify"
            result = checks.verify_backup(target, root)
        except (Exception, KeyboardInterrupt) as error:
            state["first"] = make_failure(state["stage"], error, state["key"])
            raise state["first"] from None
        finally:
            try:
                runtime.close()
            except (Exception, KeyboardInterrupt) as error:
                if state["first"] is not None:
                    attach_cleanup(state["first"], error)
                else:
                    state["first"] = make_failure("runtime_close", error)
                    raise state["first"] from None
    return result | {
        "status": "maintenance_backup_created",
        "backup_performed": True,
        "db_artifact_consistency": "maintenance_checked_source_unchanged",
        "consistency_boundary": "cooperative_single_host_maintenance",
    }
