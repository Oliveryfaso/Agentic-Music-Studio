"""Opt-in bounded single-file backups; no service lifecycle or restore execution.

The archive is the backup object. Platform files beside it are not restored.
Completion is a checked logical boundary, not atomic publication or power-loss proof.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

if __package__:
    from . import personal_beta_backup as checks
    from . import personal_beta_backup_archive as archive
    from . import personal_beta_backup_create as legacy
    from .personal_beta_backup_failure import attach_cleanup, make_failure
else:
    import personal_beta_backup as checks
    import personal_beta_backup_archive as archive
    import personal_beta_backup_create as legacy
    from personal_beta_backup_failure import attach_cleanup, make_failure


def _same_file(left, right):
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _stable(before, after):
    return _same_file(before, after) and (before.st_size, before.st_mtime_ns, before.st_nlink) == (
        after.st_size,
        after.st_mtime_ns,
        after.st_nlink,
    )


def _sealed_identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


@contextmanager
def _source_root(source):
    with archive.open_parent_fd(source, Path("/")) as (parent_fd, name):
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            legacy.require(_same_file(named, os.fstat(fd)), "BACKUP_SOURCE_CHANGED")
            yield fd
            legacy.require(
                _same_file(named, os.stat(name, dir_fd=parent_fd, follow_symlinks=False)),
                "BACKUP_SOURCE_CHANGED",
            )
        finally:
            os.close(fd)


def _hash_file(stream, before, limit):
    checksum, size = hashlib.sha256(), 0
    while chunk := stream.read(min(64 * 1024, limit - size + 1)):
        size += len(chunk)
        legacy.require(size <= limit, "BACKUP_MEDIA_BUDGET_EXCEEDED")
        checksum.update(chunk)
    legacy.require(
        _stable(before, os.fstat(stream.fileno())) and size == before.st_size,
        "BACKUP_FILE_CHANGED",
    )
    return size, checksum.hexdigest()


def inventory_v2(source):
    """Stream a bounded regular-file tree, keeping every ._* as ordinary bytes."""
    files, directories, total = [], [], 0

    def visit(fd, prefix):
        nonlocal total
        with os.scandir(fd) as entries:
            for entry in entries:
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                archive.validate_relative(relative)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    directories.append(relative)
                    legacy.require(
                        len(directories) <= archive.MAX_DIRECTORIES,
                        "BACKUP_DIRECTORY_BUDGET_EXCEEDED",
                    )
                    child = os.open(
                        entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                    try:
                        legacy.require(_same_file(info, os.fstat(child)), "BACKUP_FILE_CHANGED")
                        visit(child, relative)
                    finally:
                        os.close(child)
                else:
                    legacy.require(stat.S_ISREG(info.st_mode), "BACKUP_FILE_NOT_REGULAR")
                    legacy.require(info.st_nlink == 1, "BACKUP_HARDLINK_UNSUPPORTED")
                    legacy.require(len(files) < archive.MAX_FILES, "BACKUP_FILE_BUDGET_EXCEEDED")
                    with os.fdopen(
                        os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd),
                        "rb",
                    ) as stream:
                        opened = os.fstat(stream.fileno())
                        legacy.require(_same_file(info, opened), "BACKUP_FILE_CHANGED")
                        size, digest = _hash_file(stream, opened, archive.MAX_MEDIA_BYTES - total)
                    total += size
                    files.append({"path": relative, "bytes": size, "sha256": digest})
                legacy.require(len(files) + len(directories) <= 1024, "BACKUP_FILE_BUDGET_EXCEEDED")

    with _source_root(source) as fd:
        visit(fd, "")
    archive.validate_namespace([row["path"] for row in files], directories)
    return {"files": sorted(files, key=lambda row: row["path"]), "directories": sorted(directories)}


@contextmanager
def _source_file(source, relative):
    with _source_root(source) as root_fd:
        fd = os.dup(root_fd)
        try:
            parts = PurePosixPath(relative).parts
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            named = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                legacy.require(
                    stat.S_ISREG(opened.st_mode)
                    and opened.st_nlink == 1
                    and _same_file(named, opened),
                    "BACKUP_FILE_CHANGED",
                )
                yield stream, opened
                legacy.require(
                    _same_file(opened, os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)),
                    "BACKUP_FILE_CHANGED",
                )
        finally:
            os.close(fd)


class _BoundedArchive:
    """Seekable file adapter with a high-water byte bound, including header rewrites."""

    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        legacy.require(
            self.stream.tell() + len(data) <= archive.MAX_ARCHIVE_BYTES,
            "BACKUP_ARCHIVE_BUDGET_EXCEEDED",
        )
        result = self.stream.write(data)
        legacy.require(result == len(data), "BACKUP_ARCHIVE_SHORT_WRITE")
        return result

    def tell(self):
        return self.stream.tell()

    def seek(self, offset, whence=0):
        result = self.stream.seek(offset, whence)
        legacy.require(0 <= result <= archive.MAX_ARCHIVE_BYTES, "BACKUP_ARCHIVE_BUDGET_EXCEEDED")
        return result

    def flush(self):
        self.stream.flush()


class _PayloadSink:
    def __init__(self, stream, limit, code):
        self.stream, self.limit, self.code = stream, limit, code
        self.size, self.digest, self.header = 0, hashlib.sha256(), b""

    def write(self, data):
        legacy.require(len(data) <= self.limit - self.size, self.code)
        written = self.stream.write(data)
        legacy.require(written == len(data), "BACKUP_ARCHIVE_SHORT_WRITE")
        self.size += len(data)
        self.digest.update(data)
        if len(self.header) < 8:
            self.header += data[: 8 - len(self.header)]
        return written

    def flush(self):
        # ZipExtFile has no flush contract; the owning archive is closed and fsynced.
        pass

    def tell(self):
        return self.size

    def row(self, path):
        return {"path": path, "bytes": self.size, "sha256": self.digest.hexdigest()}


def _info(name, *, directory=False):
    result = zipfile.ZipInfo(name)
    result.create_system, result.create_version, result.extract_version = 3, 20, 20
    result.compress_type = zipfile.ZIP_STORED
    mode = (stat.S_IFDIR | 0o700) if directory else (stat.S_IFREG | 0o600)
    result.external_attr = (mode << 16) | (0x10 if directory else 0)
    return result


def _runtime_factory(contract):
    if __package__:
        from .personal_beta_backup_runtime import DockerBackupRuntime
    else:
        from personal_beta_backup_runtime import DockerBackupRuntime
    return DockerBackupRuntime(contract)


def _create_locked(contract, source, target, state, factory):
    runtime, first, stream, output = None, None, None, None
    try:
        state["stage"] = "writer_quiescence"
        runtime = factory(contract)
        runtime.assert_quiescent()
        state["stage"] = "inventory_before"
        source_identity = source.stat()
        before = inventory_v2(source)
        state["stage"] = "database_snapshot_before"
        db_before = runtime.snapshot()
        legacy.require(
            db_before.get("database") == "motif_forge"
            and db_before.get("schema_revision") == legacy.REVISION,
            "BACKUP_DATABASE_MISMATCH",
        )
        required = (
            sum(row["bytes"] for row in before["files"])
            + archive.MAX_DUMP_BYTES
            + archive.MAX_MANIFEST_BYTES
            + archive.MAX_CENTRAL_BYTES
        )
        state["stage"] = "target_create"
        space = os.statvfs(target.parent)
        legacy.require(
            space.f_bavail * space.f_frsize >= required, "BACKUP_TARGET_SPACE_INSUFFICIENT"
        )
        with archive.open_parent_fd(target, Path(contract["allowed_root"])) as (parent_fd, name):
            raw_fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        stream = os.fdopen(raw_fd, "w+b")
        identity = os.fstat(stream.fileno())
        legacy.require(
            stat.S_ISREG(identity.st_mode) and identity.st_nlink == 1, "BACKUP_TARGET_CHANGED"
        )
        state["stage"] = "archive_open"
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = zipfile.ZipFile(_BoundedArchive(stream), "w", allowZip64=False)
        state["stage"] = "dump_write"
        with output.open(_info("dump/beta.pgdump"), "w") as member:
            sink = _PayloadSink(member, archive.MAX_DUMP_BYTES, "BACKUP_DUMP_BUDGET_EXCEEDED")
            runtime.dump(sink, archive.MAX_DUMP_BYTES)
            legacy.require(
                sink.size > 5 and sink.header.startswith(b"PGDMP"), "BACKUP_DUMP_INVALID"
            )
            dump = sink.row("dump/beta.pgdump")
        state["stage"] = "artifact_copy"
        for index, relative in enumerate(before["directories"]):
            state["key"] = relative
            state["index"] = index
            output.writestr(_info("media/" + relative + "/", directory=True), b"")
        for index, row in enumerate(before["files"], len(before["directories"])):
            state["key"] = row["path"]
            state["index"] = index
            with (
                _source_file(source, row["path"]) as (inp, opened),
                output.open(_info("media/" + row["path"]), "w") as member,
            ):
                copied = _PayloadSink(member, row["bytes"], "BACKUP_FILE_CHANGED")
                while chunk := inp.read(min(64 * 1024, row["bytes"] - copied.size + 1)):
                    copied.write(chunk)
                legacy.require(
                    copied.row(row["path"]) == row and _stable(opened, os.fstat(inp.fileno())),
                    "BACKUP_FILE_CHANGED",
                )
        state["key"] = None
        state["index"] = None
        state["stage"] = "inventory_after"
        legacy.require(
            inventory_v2(source) == before and _same_file(source_identity, source.stat()),
            "BACKUP_SOURCE_CHANGED",
        )
        state["stage"] = "database_snapshot_after"
        legacy.require(runtime.snapshot() == db_before, "BACKUP_DATABASE_CHANGED")
        state["stage"] = "writer_quiescence"
        runtime.assert_quiescent()
        manifest = {
            "schema_version": "motif-beta-maintenance-backup.v2",
            "source_root": str(source),
            **before,
            "db_dump": dump,
            "db_tables": db_before["tables"],
            "db_sequences": db_before["sequences"],
            "schema_revision": legacy.REVISION,
            "source_identity": {
                key: contract[key]
                for key in ("daemon_id", "compose_project", "owner", "containers", "images")
            },
            "consistency_boundary": "cooperative_single_host_maintenance",
            "database_restore_tested": False,
        }
        state["stage"] = "archive_manifest"
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        legacy.require(len(raw) <= archive.MAX_MANIFEST_BYTES, "BACKUP_MANIFEST_BUDGET_EXCEEDED")
        output.writestr(_info("manifest.json"), raw)
        state["stage"] = "archive_close"
        closing, output = output, None
        closing.close()
        state["stage"] = "archive_fsync"
        stream.flush()
        os.fsync(stream.fileno())
        state["stage"] = "archive_verify"
        sealed = os.fstat(stream.fileno())
        legacy.require(sealed.st_nlink == 1, "BACKUP_TARGET_CHANGED")
        stream.seek(0)
        _, result = archive.verify_stream(stream)
        with archive.open_parent_fd(target, Path(contract["allowed_root"])) as (parent_fd, name):
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        legacy.require(
            _same_file(identity, named)
            and _sealed_identity(sealed) == _sealed_identity(os.fstat(stream.fileno()))
            and _sealed_identity(sealed) == _sealed_identity(named),
            "BACKUP_TARGET_CHANGED",
        )
        state["stage"] = "archive_close"
        closing, stream = stream, None
        closing.close()
        return result | {
            "status": "maintenance_backup_created",
            "backup_performed": True,
            "format": "archive-v2",
            "db_artifact_consistency": "maintenance_checked_source_unchanged",
            "consistency_boundary": "cooperative_single_host_maintenance",
        }
    except (Exception, KeyboardInterrupt) as error:
        first = make_failure(state["stage"], error, state.get("key"), item_index=state.get("index"))
        state["first"] = first
        raise first from None
    finally:
        for resource in (output, stream, runtime):
            if resource is None:
                continue
            try:
                state["stage"] = "runtime_close" if resource is runtime else "archive_close"
                resource.close()
            except (Exception, KeyboardInterrupt) as error:
                if first is None:
                    first = make_failure(state["stage"], error)
                    state["first"] = first
                else:
                    attach_cleanup(first, error)
        if first is not None:
            raise first from None


def create_archive_backup(contract, *, execute=False, factory=None):
    state = {"stage": "contract", "key": None, "index": None, "first": None}
    try:
        root, source, target = legacy.validate_contract(contract)
        if not execute:
            return checks.plan_backup(source, target, root) | {
                "format": "archive-v2",
                "execution_requires_maintenance": True,
                "supported_schema": legacy.REVISION,
            }
        state["stage"] = "maintenance_lock"
        with legacy.maintenance_lock(contract):
            return _create_locked(contract, source, target, state, factory or _runtime_factory)
    except (Exception, KeyboardInterrupt) as error:
        first = state["first"]
        if first is None:
            first = make_failure(
                state["stage"], error, state.get("key"), item_index=state.get("index")
            )
        elif error is not first:
            attach_cleanup(first, error)
        raise first from None
