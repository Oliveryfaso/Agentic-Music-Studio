"""Bounded reader for Motif's opt-in, uncompressed single-file backup v2.

This is deliberately not a general ZIP importer. Verification covers the one
archive file, not its parent directory, filesystem metadata, or DB restore.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import struct
import unicodedata
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

if __package__:
    from . import personal_beta_backup as checks
else:
    import personal_beta_backup as checks

MAX_FILES = checks.MAX_FILES
MAX_MEDIA_BYTES = checks.MAX_MEDIA_BYTES
MAX_DUMP_BYTES = checks.MAX_DUMP_BYTES
MAX_MANIFEST_BYTES = checks.MAX_MANIFEST_BYTES
MAX_DIRECTORIES = 768
MAX_PATH_BYTES = 1024
MAX_DEPTH = 32
MAX_ENTRIES = 1026
MAX_CENTRAL_BYTES = 2 * 1024**2
MAX_ARCHIVE_BYTES = 195 * 1024**2
SCHEMA = "motif-beta-maintenance-backup.v2"
_EOCD = struct.Struct("<4s4H2IH")
_CENTRAL = struct.Struct("<4s6H3I5H2I")
_LOCAL = struct.Struct("<4s5H3I2H")
_FIELDS = frozenset(
    (
        "schema_version",
        "source_root",
        "schema_revision",
        "files",
        "directories",
        "db_dump",
        "db_tables",
        "db_sequences",
        "source_identity",
        "consistency_boundary",
        "database_restore_tested",
    )
)


def require(condition, code="BACKUP_ARCHIVE_INVALID"):
    checks._require(condition, code)


def validate_relative(name):
    require(isinstance(name, str), "BACKUP_MANIFEST_PATH_INVALID")
    try:
        encoded = name.encode("utf-8")
    except UnicodeError:
        raise checks.BackupCheckError("BACKUP_MANIFEST_PATH_INVALID") from None
    path = PurePosixPath(name)
    require(
        0 < len(encoded) <= MAX_PATH_BYTES
        and "\x00" not in name
        and "\\" not in name
        and not path.is_absolute()
        and path.as_posix() == name
        and len(path.parts) <= MAX_DEPTH
        and all(part not in ("", ".", "..") for part in name.split("/")),
        "BACKUP_MANIFEST_PATH_INVALID",
    )
    return name


def validate_namespace(files_names, dir_names):
    files, directories = list(files_names), list(dir_names)
    require(
        len(files) <= MAX_FILES
        and len(directories) <= MAX_DIRECTORIES
        and len(files) + len(directories) <= MAX_ENTRIES - 2,
        "BACKUP_FILE_BUDGET_EXCEEDED",
    )
    seen = set()
    for name in files + directories:
        validate_relative(name)
        canonical = unicodedata.normalize("NFC", name).casefold()
        require(canonical not in seen, "BACKUP_RESTORE_NAME_COLLISION")
        seen.add(canonical)
    dir_set = set(directories)
    for name in files + directories:
        parents = PurePosixPath(name).parents
        require(
            all(parent.as_posix() in dir_set for parent in parents if parent.as_posix() != "."),
            "BACKUP_RESTORE_PARENT_MISSING",
        )


def _read_exact(stream, count):
    value = stream.read(count)
    require(len(value) == count)
    return value


def _eocd(stream):
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    require(22 <= size <= MAX_ARCHIVE_BYTES, "BACKUP_ARCHIVE_BUDGET_EXCEEDED")
    stream.seek(size - _EOCD.size)
    sig, disk, central_disk, disk_count, count, length, offset, comment = _EOCD.unpack(
        _read_exact(stream, _EOCD.size)
    )
    require(
        sig == b"PK\x05\x06"
        and disk == central_disk == comment == 0
        and count == disk_count
        and 2 <= count <= MAX_ENTRIES
        and 0 < length <= MAX_CENTRAL_BYTES
        and 0 < offset < size
        and offset + length == size - _EOCD.size,
        "BACKUP_ARCHIVE_STRUCTURE_INVALID",
    )
    return size, count, offset, length


def _structure(stream, archive, count, central_offset, central_length):
    infos = archive.infolist()
    require(len(infos) == count, "BACKUP_ARCHIVE_STRUCTURE_INVALID")
    central_position, expected_local = central_offset, 0
    names = []
    for info in infos:
        stream.seek(central_position)
        values = _CENTRAL.unpack(_read_exact(stream, _CENTRAL.size))
        (
            sig,
            made,
            needed,
            flags,
            method,
            stamp,
            date,
            crc,
            compressed,
            size,
            name_length,
            extra_length,
            comment_length,
            disk,
            internal,
            external,
            local_offset,
        ) = values
        require(
            sig == b"PK\x01\x02"
            and made == (3 << 8 | 20)
            and needed == 20
            and flags in (0, 0x800)
            and method == zipfile.ZIP_STORED
            and extra_length == comment_length == disk == internal == 0
            and 0 < name_length <= MAX_PATH_BYTES + 7
            and compressed == size
            and local_offset == expected_local,
            "BACKUP_ARCHIVE_STRUCTURE_INVALID",
        )
        raw_name = _read_exact(stream, name_length)
        try:
            name = raw_name.decode("utf-8" if flags else "ascii")
        except UnicodeError:
            raise checks.BackupCheckError("BACKUP_ARCHIVE_STRUCTURE_INVALID") from None
        require(
            name == info.filename
            and info.orig_filename == name
            and info.header_offset == local_offset
            and info.flag_bits == flags
            and crc == info.CRC
            and info.file_size == size
            and info.compress_size == size
            and not info.extra
            and not info.comment,
            "BACKUP_ARCHIVE_STRUCTURE_INVALID",
        )
        directory = name.endswith("/")
        mode = external >> 16
        require(
            (stat.S_ISDIR(mode) and directory and size == crc == 0 and external & 0xFFFF == 0x10)
            or (stat.S_ISREG(mode) and not directory and external & 0xFFFF == 0),
            "BACKUP_ARCHIVE_SPECIAL_FILE",
        )
        require(name not in names, "BACKUP_ARCHIVE_DUPLICATE")
        names.append(name)
        stream.seek(local_offset)
        local = _LOCAL.unpack(_read_exact(stream, _LOCAL.size))
        require(
            local
            == (b"PK\x03\x04", needed, flags, method, stamp, date, crc, size, size, name_length, 0),
            "BACKUP_ARCHIVE_STRUCTURE_INVALID",
        )
        require(_read_exact(stream, name_length) == raw_name, "BACKUP_ARCHIVE_STRUCTURE_INVALID")
        expected_local = local_offset + _LOCAL.size + name_length + size
        require(expected_local <= central_offset, "BACKUP_ARCHIVE_STRUCTURE_INVALID")
        central_position += _CENTRAL.size + name_length
        require(central_position <= central_offset + central_length)
    require(
        expected_local == central_offset
        and central_position == central_offset + central_length
        and names[0] == "dump/beta.pgdump"
        and names[-1] == "manifest.json"
        and all(name.startswith("media/") for name in names[1:-1]),
        "BACKUP_ARCHIVE_STRUCTURE_INVALID",
    )
    return infos


def _unique_json(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "BACKUP_MANIFEST_DUPLICATE")
        value[key] = item
    return value


def _load_manifest(archive, info):
    require(info.file_size <= MAX_MANIFEST_BYTES, "BACKUP_MANIFEST_BUDGET_EXCEEDED")
    with archive.open(info) as source:
        raw = source.read(MAX_MANIFEST_BYTES + 1)
    require(len(raw) == info.file_size <= MAX_MANIFEST_BYTES, "BACKUP_MANIFEST_BUDGET_EXCEEDED")
    result = json.loads(raw, object_pairs_hook=_unique_json)
    require(isinstance(result, dict) and set(result) == _FIELDS, "BACKUP_MANIFEST_INVALID")
    require(result["schema_version"] == SCHEMA, "BACKUP_SCHEMA_UNSUPPORTED")
    require(
        isinstance(result["files"], list)
        and isinstance(result["directories"], list)
        and isinstance(result["db_tables"], list)
        and isinstance(result["db_sequences"], list)
        and isinstance(result["source_identity"], dict)
        and result["database_restore_tested"] is False
        and result["consistency_boundary"] == "cooperative_single_host_maintenance"
        and isinstance(result["source_root"], str)
        and Path(result["source_root"]).is_absolute()
        and ".." not in Path(result["source_root"]).parts
        and isinstance(result["schema_revision"], str)
        and re.fullmatch(r"[0-9]{8}_[0-9]{4}", result["schema_revision"]),
        "BACKUP_MANIFEST_INVALID",
    )
    return result


def _row(row):
    require(
        isinstance(row, dict) and set(row) == {"path", "bytes", "sha256"}, "BACKUP_MANIFEST_INVALID"
    )
    validate_relative(row["path"])
    require(type(row["bytes"]) is int and row["bytes"] >= 0, "BACKUP_MANIFEST_INVALID")
    require(
        isinstance(row["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
        "BACKUP_MANIFEST_INVALID",
    )
    return row


def _digest_member(archive, info, row, limit, dump=False):
    require(info.file_size == row["bytes"] <= limit, "BACKUP_FILE_BUDGET_EXCEEDED")
    checksum, total, header = hashlib.sha256(), 0, b""
    with archive.open(info) as source:
        while chunk := source.read(64 * 1024):
            if not header:
                header = chunk[:8]
            total += len(chunk)
            require(total <= row["bytes"] <= limit, "BACKUP_FILE_BUDGET_EXCEEDED")
            checksum.update(chunk)
    require(total == row["bytes"] and checksum.hexdigest() == row["sha256"], "BACKUP_FILE_MISMATCH")
    if dump:
        require(total > 5 and header.startswith(b"PGDMP"), "BACKUP_DUMP_INVALID")


def verify_stream(stream):
    """Validate a caller-held, stable seekable stream; caller owns its lock."""
    try:
        _size, count, offset, length = _eocd(stream)
        stream.seek(0)
        with zipfile.ZipFile(stream, "r", allowZip64=False) as archive:
            infos = _structure(stream, archive, count, offset, length)
            manifest = _load_manifest(archive, infos[-1])
            rows = [_row(row) for row in manifest["files"]]
            dirs = manifest["directories"]
            validate_namespace([row["path"] for row in rows], dirs)
            dump = _row(manifest["db_dump"])
            require(dump["path"] == "dump/beta.pgdump", "BACKUP_DUMP_PATH_INVALID")
            expected = {"dump/beta.pgdump", "manifest.json"}
            expected.update("media/" + row["path"] for row in rows)
            expected.update("media/" + name + "/" for name in dirs)
            require(
                {info.filename for info in infos} == expected, "BACKUP_UNLISTED_OR_MISSING_FILES"
            )
            media_bytes = sum(row["bytes"] for row in rows)
            require(media_bytes <= MAX_MEDIA_BYTES, "BACKUP_MEDIA_BUDGET_EXCEEDED")
            by_name = {info.filename: info for info in infos}
            _digest_member(archive, infos[0], dump, MAX_DUMP_BYTES, dump=True)
            for row in rows:
                _digest_member(archive, by_name["media/" + row["path"]], row, MAX_MEDIA_BYTES)
            return manifest, {
                "schema_version": SCHEMA,
                "integrity": "verified",
                "artifact_files": len(rows),
                "artifact_bytes": media_bytes,
                "artifact_directories": len(dirs),
                "dump_bytes": dump["bytes"],
                "database_restore_tested": False,
                "db_artifact_consistency": "not_proven_by_integrity_check",
                "verified_scope": "archive_file_only",
            }
    except checks.BackupCheckError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, EOFError, struct.error):
        raise checks.BackupCheckError("BACKUP_ARCHIVE_INVALID") from None


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def open_parent_fd(path, allowed_root):
    """Pin every directory component; never follow a swapped parent symlink."""
    require(
        path.is_absolute()
        and allowed_root.is_absolute()
        and ".." not in path.parts
        and ".." not in allowed_root.parts
        and allowed_root in path.parents,
        "BACKUP_PATH_OUTSIDE_ROOT",
    )
    descriptor = None
    try:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in path.parent.parts[1:]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        yield descriptor, path.name
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _locked_archive(path, allowed_root):
    root = checks._root(allowed_root)
    path = checks._inside(path, root)
    with open_parent_fd(path, root) as (parent_fd, name):
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "BACKUP_FILE_NOT_REGULAR")
        opened_fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        with os.fdopen(opened_fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            require(_identity(before) == _identity(opened), "BACKUP_FILE_CHANGED")
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise checks.BackupCheckError("BACKUP_ARCHIVE_BUSY") from None
            yield stream
            require(
                _identity(before)
                == _identity(os.fstat(stream.fileno()))
                == _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)),
                "BACKUP_FILE_CHANGED",
            )


def verify_archive(path: Path, allowed_root: Path):
    try:
        with _locked_archive(path, allowed_root) as stream:
            return verify_stream(stream)[1]
    except OSError:
        raise checks.BackupCheckError("BACKUP_ARCHIVE_IO_ERROR") from None


def plan_restore_archive(path: Path, target: Path, allowed_root: Path):
    try:
        return _plan_restore_archive(path, target, allowed_root)
    except OSError:
        raise checks.BackupCheckError("BACKUP_ARCHIVE_IO_ERROR") from None


def _plan_restore_archive(path: Path, target: Path, allowed_root: Path):
    with _locked_archive(path, allowed_root) as stream:
        manifest, result = verify_stream(stream)
        root = checks._root(allowed_root)
        target = checks._inside(target, root, exists=False)
        source = Path(manifest["source_root"])
        require(not target.exists(), "BACKUP_TARGET_NOT_FRESH")
        require(
            not checks._overlap(target, path) and not checks._overlap(target, source),
            "BACKUP_TARGET_OVERLAPS_SOURCE",
        )
        require(target.parent.is_dir(), "BACKUP_TARGET_PARENT_MISSING")
        space = os.statvfs(target.parent)
        require(
            space.f_bavail * space.f_frsize
            >= result["artifact_bytes"] + result["dump_bytes"] + 1024**2,
            "BACKUP_TARGET_SPACE_INSUFFICIENT",
        )
        return result | {
            "status": "restore_dry_run_only",
            "restore_performed": False,
            "ready_for_real_restore": False,
            "required_evidence": [
                "distinct_empty_database",
                "exclusive_item_creation",
                "matching_schema_and_readers",
                "isolated_restore_verified",
            ],
        }
