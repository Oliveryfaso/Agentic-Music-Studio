"""Synthetic v2 archives only: no real DB, Docker, or source media."""

import fcntl
import hashlib
import importlib
import io
import json
import os
import stat
import struct
import zipfile

import pytest


def module():
    return importlib.import_module("scripts.personal_beta_backup_archive")


def member(name, directory=False):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (
        ((stat.S_IFDIR | 0o700) << 16 | 0x10) if directory else ((stat.S_IFREG | 0o600) << 16)
    )
    info.compress_type = zipfile.ZIP_STORED
    return info


def row(path, value):
    return {"path": path, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def archive(*, files=None, directories=None, change=None, extra=None):
    files = (
        {"audio.wav": b"synthetic", "._real-user-file": b"real user bytes"}
        if files is None
        else files
    )
    directories = ["empty"] if directories is None else directories
    dump = b"PGDMP\x00synthetic"
    manifest = {
        "schema_version": "motif-beta-maintenance-backup.v2",
        "source_root": "/synthetic/source",
        "schema_revision": "20261020_0030",
        "files": [row(name, value) for name, value in files.items()],
        "directories": directories,
        "db_dump": row("dump/beta.pgdump", dump),
        "db_tables": [],
        "db_sequences": [],
        "source_identity": {},
        "consistency_boundary": "cooperative_single_host_maintenance",
        "database_restore_tested": False,
    }
    if change:
        change(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as writer:
        writer.writestr(member("dump/beta.pgdump"), dump)
        for name in directories:
            writer.writestr(member("media/" + name + "/", True), b"")
        for name, value in files.items():
            writer.writestr(member("media/" + name), value)
        if extra:
            writer.writestr(member(extra), b"unexpected")
        writer.writestr(member("manifest.json"), json.dumps(manifest).encode())
    return output.getvalue()


def test_v2_stream_preserves_real_dot_underscore_and_empty_directory():
    manifest, result = module().verify_stream(io.BytesIO(archive()))
    assert manifest["directories"] == ["empty"]
    assert "._real-user-file" in {x["path"] for x in manifest["files"]}
    assert result["integrity"] == "verified"
    assert result["database_restore_tested"] is False


@pytest.mark.parametrize(
    "name", ["/absolute", "../escape", "a/../b", "a\\b", "a//b", "a/./b", "a\x00b", ".", ""]
)
def test_reject_noncanonical_paths(name):
    with pytest.raises(ValueError):
        module().validate_relative(name)


@pytest.mark.parametrize(
    "files,dirs",
    [
        (["A", "a"], []),
        (["é", "e\u0301"], []),
        (["a", "a/b"], ["a"]),
        (["a"], ["a"]),
        (["a/b"], []),
    ],
)
def test_reject_restore_namespace_collisions_or_missing_parent(files, dirs):
    with pytest.raises(ValueError):
        module().validate_namespace(files, dirs)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(schema_version="unknown"),
        lambda m: m["files"][0].update(sha256="0" * 64),
        lambda m: m["files"].append(m["files"][0]),
        lambda m: m["db_dump"].update(path="other"),
    ],
)
def test_manifest_rejects_unknown_version_tamper_duplicate_and_dump_path(mutation):
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(archive(change=mutation)))


@pytest.mark.parametrize(
    "transform", [lambda b: b"hidden" + b, lambda b: b + b"trailing", lambda b: b[:-4]]
)
def test_reject_prefix_trailing_and_truncation(transform):
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(transform(archive())))


def test_reject_unlisted_member():
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(archive(extra="media/unlisted")))


def test_reject_duplicate_zip_member():
    data = io.BytesIO(archive())
    with (
        zipfile.ZipFile(data, "a") as writer,
        pytest.warns(UserWarning, match="Duplicate name"),
    ):
        writer.writestr(member("media/audio.wav"), b"duplicate")
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(data.getvalue()))


def test_reject_out_of_bounds_central_before_loading_zipfile(monkeypatch):
    data = bytearray(archive())
    struct.pack_into("<I", data, len(data) - 10, 3 * 1024**2)
    monkeypatch.setattr(
        zipfile, "ZipFile", lambda *_a, **_kw: pytest.fail("unbounded ZipFile loaded")
    )
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(data))


def test_verify_path_shared_lock_and_external_sidecar_not_restored(tmp_path):
    path = tmp_path / "backup.zip"
    path.write_bytes(archive())
    (tmp_path / "._backup.zip").write_bytes(b"platform metadata outside backup")
    with path.open("rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="BACKUP_ARCHIVE_BUSY"):
            module().verify_archive(path, tmp_path)
    assert module().verify_archive(path, tmp_path)["artifact_files"] == 2
    target = tmp_path / "restored"
    result = module().plan_restore_archive(path, target, tmp_path)
    assert result["restore_performed"] is False and not target.exists()


def test_restore_plan_rejects_existing_target_without_writing(tmp_path):
    path = tmp_path / "backup.zip"
    path.write_bytes(archive())
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(ValueError):
        module().plan_restore_archive(path, target, tmp_path)
    assert list(target.iterdir()) == []


def test_reject_symlink_and_hardlink_archive(tmp_path):
    path = tmp_path / "backup.zip"
    path.write_bytes(archive())
    link = tmp_path / "link.zip"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        module().verify_archive(link, tmp_path)
    hard = tmp_path / "hard.zip"
    os.link(path, hard)
    with pytest.raises(ValueError):
        module().verify_archive(path, tmp_path)


def test_empty_real_dot_underscore_file_is_data():
    manifest, result = module().verify_stream(io.BytesIO(archive(files={"._empty": b""})))
    assert manifest["files"][0]["bytes"] == 0
    assert result["artifact_files"] == 1


def offsets(data):
    central = struct.unpack_from("<I", data, len(data) - 6)[0]
    return 0, central


@pytest.mark.parametrize("field,value", [(6, 1), (6, 8), (8, 8)])
def test_reject_encryption_descriptor_or_compression(field, value):
    data = bytearray(archive())
    local, central = offsets(data)
    struct.pack_into("<H", data, local + field, value)
    struct.pack_into("<H", data, central + field + 2, value)
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(data))


def test_reject_symlink_member_attribute():
    data = bytearray(archive())
    _, central = offsets(data)
    struct.pack_into("<I", data, central + 38, (stat.S_IFLNK | 0o600) << 16)
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(data))


@pytest.mark.parametrize("field,value", [(14, 123), (22, 0)])
def test_local_header_must_match_central(field, value):
    data = bytearray(archive())
    struct.pack_into("<I", data, field, value)
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(data))


def test_reject_overlapping_local_header():
    data = bytearray(archive())
    _, central = offsets(data)
    first_name_length = struct.unpack_from("<H", data, central + 28)[0]
    second = central + 46 + first_name_length
    struct.pack_into("<I", data, second + 42, 0)
    with pytest.raises(ValueError):
        module().verify_stream(io.BytesIO(data))


def test_enforce_archive_manifest_media_and_path_budgets(monkeypatch):
    reader = module()
    data = archive()
    monkeypatch.setattr(reader, "MAX_ARCHIVE_BYTES", len(data) - 1)
    with pytest.raises(ValueError, match="BUDGET"):
        reader.verify_stream(io.BytesIO(data))
    monkeypatch.setattr(reader, "MAX_ARCHIVE_BYTES", len(data) + 1)
    monkeypatch.setattr(reader, "MAX_MANIFEST_BYTES", 5)
    with pytest.raises(ValueError, match="MANIFEST_BUDGET"):
        reader.verify_stream(io.BytesIO(data))
    monkeypatch.setattr(reader, "MAX_MANIFEST_BYTES", 1024**2)
    monkeypatch.setattr(reader, "MAX_MEDIA_BYTES", 1)
    with pytest.raises(ValueError, match="MEDIA_BUDGET"):
        reader.verify_stream(io.BytesIO(data))
    with pytest.raises(ValueError):
        reader.validate_relative("a" * 1025)
    with pytest.raises(ValueError):
        reader.validate_relative("/".join("a" for _ in range(33)))


def test_full_verification_keeps_shared_lock_and_detects_identity_change(tmp_path, monkeypatch):
    reader = module()
    path = tmp_path / "backup.zip"
    path.write_bytes(archive())
    original = reader.verify_stream

    def check(stream):
        with path.open("rb") as second, pytest.raises(BlockingIOError):
            fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = original(stream)
        before = path.stat()
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
        return result

    monkeypatch.setattr(reader, "verify_stream", check)
    with pytest.raises(ValueError, match="BACKUP_FILE_CHANGED"):
        reader.verify_archive(path, tmp_path)


def test_parent_directory_swap_cannot_read_archive_outside_allowed_root(tmp_path, monkeypatch):
    reader = module()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    parent = allowed / "inside"
    parent.mkdir()
    path = parent / "backup.zip"
    path.write_bytes(archive())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "backup.zip").write_bytes(archive())
    original = reader.checks._inside
    changed = False

    def resolve_then_swap(candidate, root, **kwargs):
        nonlocal changed
        result = original(candidate, root, **kwargs)
        if candidate == path and not changed:
            changed = True
            parent.rename(allowed / "saved")
            parent.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(reader.checks, "_inside", resolve_then_swap)
    with pytest.raises(ValueError):
        reader.verify_archive(path, allowed)
