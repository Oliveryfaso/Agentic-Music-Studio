"""Opt-in archive creation with synthetic source bytes and a DB boundary stub."""

import errno
import fcntl
import importlib
import json
import os
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest


@pytest.fixture
def creator():
    try:
        return importlib.import_module("scripts.personal_beta_backup_archive_create")
    except ModuleNotFoundError:
        pytest.fail("opt-in archive creation is missing")


@pytest.fixture
def contract(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "audio.wav").write_bytes(b"synthetic audio")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (runtime / "operation.lock").touch(mode=0o600)
    record = {
        "schema": "motif-owned-stack.v1",
        "project_root": str(tmp_path),
        "compose_project": "motif-archive-test",
        "daemon_id": "test-daemon",
        "owner": "11111111-1111-4111-8111-111111111111",
    }
    (runtime / "stack.json").write_text(json.dumps(record))
    (runtime / "stack.json").chmod(0o600)
    roles = (
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
    return {
        "schema": "motif-beta-backup-create.v1",
        "allowed_root": str(tmp_path),
        "source": str(source),
        "destination": str(tmp_path / "backup.motif.zip"),
        "runtime_dir": str(runtime),
        **{k: v for k, v in record.items() if k != "schema"},
        "containers": {s: f"{i:064x}" for i, s in enumerate(roles, 1)},
        "images": {s: "sha256:" + f"{i:064x}" for i, s in enumerate(roles, 1)},
        "expected_db_revision": "20261020_0030",
    }


class DatabaseStub:
    def __init__(self):
        self.closed = False
        self.calls = []

    def assert_quiescent(self):
        self.calls.append("quiescent")

    def snapshot(self):
        self.calls.append("snapshot")
        return {
            "database": "motif_forge",
            "schema_revision": "20261020_0030",
            "tables": [],
            "sequences": [],
        }

    def dump(self, target, max_bytes):
        self.calls.append("dump")
        assert max_bytes == 64 * 1024**2
        assert target.tell() == 0
        target.write(b"PGDMP\0synthetic-only")
        assert target.tell() == len(b"PGDMP\0synthetic-only")

    def close(self):
        self.closed = True


def test_archive_default_is_plan_without_runtime_or_new_file(creator, contract):
    result = creator.create_archive_backup(
        contract, factory=lambda _: pytest.fail("default constructed runtime")
    )
    assert result["backup_performed"] is False
    assert result["format"] == "archive-v2"
    assert not Path(contract["destination"]).exists()


def test_real_dotunderscore_empty_file_and_directory_are_preserved(creator, contract):
    source = Path(contract["source"])
    (source / "._real-user-file").write_bytes(b"not AppleDouble; never discard")
    (source / "empty-file").touch()
    (source / "empty-directory").mkdir()
    runtime = DatabaseStub()
    result = creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert result["backup_performed"] is True
    assert result["database_restore_tested"] is False
    assert runtime.closed
    with zipfile.ZipFile(contract["destination"]) as archive:
        assert archive.namelist()[0] == "dump/beta.pgdump"
        assert archive.namelist()[-1] == "manifest.json"
        assert archive.read("media/._real-user-file") == b"not AppleDouble; never discard"
        assert archive.read("media/empty-file") == b""
        assert "media/empty-directory/" in archive.namelist()
        assert all(i.compress_type == zipfile.ZIP_STORED for i in archive.infolist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == "motif-beta-maintenance-backup.v2"
        assert "empty-directory" in manifest["directories"]
    assert runtime.calls == ["quiescent", "snapshot", "dump", "snapshot", "quiescent"]


@pytest.mark.parametrize("kind", ["symlink", "fifo", "case", "unicode", "file_budget"])
def test_inventory_rejects_unsupported_or_ambiguous_sources_before_dump(
    creator, contract, monkeypatch, kind
):
    source = Path(contract["source"])
    if kind == "symlink":
        (source / "link").symlink_to(source / "audio.wav")
    elif kind == "fifo":
        os.mkfifo(source / "fifo")
    elif kind == "case":
        (source / "A").write_bytes(b"a")
        (source / "a").write_bytes(b"b")
        if len(list(source.iterdir())) != 3:
            pytest.skip("fixture filesystem folds case")
    elif kind == "unicode":
        (source / "é").write_bytes(b"a")
        (source / "e\u0301").write_bytes(b"b")
        if len(list(source.iterdir())) != 3:
            pytest.skip("fixture filesystem normalizes Unicode")
    else:
        monkeypatch.setattr(creator.archive, "MAX_FILES", 0)
    runtime = DatabaseStub()
    with pytest.raises(ValueError):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert "dump" not in runtime.calls
    assert runtime.closed


def test_source_change_during_dump_cannot_write_manifest(creator, contract):
    runtime = DatabaseStub()
    original = runtime.dump

    def changed(target, limit):
        original(target, limit)
        Path(contract["source"], "audio.wav").write_bytes(b"changed")

    runtime.dump = changed
    with pytest.raises(ValueError, match=r"BACKUP_FILE_CHANGED|BACKUP_SOURCE_CHANGED"):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    with zipfile.ZipFile(contract["destination"]) as result:
        assert "manifest.json" not in result.namelist()


def test_database_change_cannot_write_manifest(creator, contract):
    runtime = DatabaseStub()
    original = runtime.snapshot

    def changed():
        value = original()
        if runtime.calls.count("snapshot") > 1:
            value["tables"] = [{"rows": 2}]
        return value

    runtime.snapshot = changed
    with pytest.raises(ValueError, match="BACKUP_DATABASE_CHANGED"):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    with zipfile.ZipFile(contract["destination"]) as result:
        assert "manifest.json" not in result.namelist()


def test_dump_overrun_is_bounded_and_runtime_closed(creator, contract, monkeypatch):
    monkeypatch.setattr(creator.archive, "MAX_DUMP_BYTES", 8)
    runtime = DatabaseStub()
    runtime.dump = lambda target, limit: target.write(b"PGDMP" + b"x" * 4)
    with pytest.raises(ValueError, match="BACKUP_DUMP_BUDGET_EXCEEDED"):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert runtime.closed


def test_first_dump_errno_survives_runtime_close_failure(creator, contract):
    runtime = DatabaseStub()

    def fail_dump(target, limit):
        raise OSError(errno.ENOSPC, "secret", "/private/secret-source")

    def fail_close():
        raise RuntimeError("BACKUP_REMOTE_EXEC_EXIT_UNKNOWN")

    runtime.dump, runtime.close = fail_dump, fail_close
    with pytest.raises(ValueError) as error:
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert str(error.value) == "BACKUP_IO_ERROR"
    assert error.value.diagnostic["stage"] == "dump_write"
    assert error.value.diagnostic["errno"] == errno.ENOSPC
    assert error.value.diagnostic["cleanup_code"] == "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"
    assert "secret" not in repr(error.value.diagnostic)


@pytest.mark.parametrize("stage", ["archive_close", "archive_fsync", "archive_verify"])
def test_close_fsync_or_verification_failure_never_returns_created(
    creator, contract, monkeypatch, stage
):
    runtime = DatabaseStub()
    if stage == "archive_close":
        original = zipfile.ZipFile.close

        def fail_close(self):
            was_open = self.fp is not None
            original(self)
            if was_open:
                raise OSError(errno.EIO, "private")

        monkeypatch.setattr(zipfile.ZipFile, "close", fail_close)
    elif stage == "archive_fsync":
        monkeypatch.setattr(
            creator.os, "fsync", lambda _: (_ for _ in ()).throw(OSError(errno.EIO))
        )
    else:
        monkeypatch.setattr(
            creator.archive, "verify_stream", lambda _: (_ for _ in ()).throw(ValueError("bad"))
        )
    with pytest.raises(ValueError) as error:
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert error.value.diagnostic["stage"] == stage
    assert runtime.closed


def test_target_created_after_validation_is_never_overwritten(creator, contract, monkeypatch):
    original = creator.inventory_v2
    sentinel = b"keep concurrent file"
    target = Path(contract["destination"])

    def changed(source):
        result = original(source)
        target.write_bytes(sentinel)
        return result

    monkeypatch.setattr(creator, "inventory_v2", changed)
    with pytest.raises(ValueError):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: DatabaseStub())
    assert target.read_bytes() == sentinel


def test_lock_is_held_through_full_verify_and_released_after_close(creator, contract, monkeypatch):
    original = creator.archive.verify_stream
    observations = []

    def verify(stream):
        with (
            Path(contract["destination"]).open("rb") as other,
            pytest.raises(BlockingIOError),
        ):
            fcntl.flock(other.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        observations.append("exclusive held")
        return original(stream)

    monkeypatch.setattr(creator.archive, "verify_stream", verify)
    creator.create_archive_backup(contract, execute=True, factory=lambda _: DatabaseStub())
    assert observations == ["exclusive held"]
    with Path(contract["destination"]).open("rb") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)


@pytest.mark.parametrize("budget", ["media", "directory", "archive"])
def test_budget_failures_are_bounded_and_close_runtime(creator, contract, monkeypatch, budget):
    runtime = DatabaseStub()
    if budget == "media":
        monkeypatch.setattr(creator.archive, "MAX_MEDIA_BYTES", 2)
    elif budget == "directory":
        Path(contract["source"], "directory").mkdir()
        monkeypatch.setattr(creator.archive, "MAX_DIRECTORIES", 0)
    else:
        monkeypatch.setattr(creator.archive, "MAX_ARCHIVE_BYTES", 12)
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert runtime.closed


def test_hardlinked_source_is_explicitly_unsupported(creator, contract):
    source = Path(contract["source"])
    os.link(source / "audio.wav", source / "linked")
    with pytest.raises(ValueError, match="BACKUP_HARDLINK_UNSUPPORTED"):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: DatabaseStub())


def test_copy_will_not_follow_swapped_ancestor_directory(creator, contract, tmp_path):
    source = Path(contract["source"])
    directory = source / "directory"
    directory.mkdir()
    (directory / "safe").write_bytes(b"safe source")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "safe").write_bytes(b"private sentinel")
    runtime = DatabaseStub()
    original = runtime.dump

    def swap(target, limit):
        original(target, limit)
        directory.rename(source / "former-directory")
        directory.symlink_to(outside, target_is_directory=True)

    runtime.dump = swap
    with pytest.raises(ValueError):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert b"private sentinel" not in Path(contract["destination"]).read_bytes()


def test_copied_file_path_replacement_is_detected(creator, contract, monkeypatch):
    source = Path(contract["source"])
    original = creator._PayloadSink.write
    replaced = False

    def replace_during_copy(self, data):
        nonlocal replaced
        result = original(self, data)
        if data == b"synthetic audio" and not replaced:
            replaced = True
            (source / "audio.wav").rename(source / "former.wav")
            (source / "audio.wav").write_bytes(data)
        return result

    monkeypatch.setattr(creator._PayloadSink, "write", replace_during_copy)
    with pytest.raises(ValueError, match="BACKUP_FILE_CHANGED") as error:
        creator.create_archive_backup(contract, execute=True, factory=lambda _: DatabaseStub())
    assert error.value.diagnostic["item_index"] == 0
    assert "audio.wav" not in repr(error.value.diagnostic)


def test_final_writer_quiescence_is_required_before_manifest(creator, contract):
    runtime = DatabaseStub()
    original = runtime.assert_quiescent

    def running():
        original()
        if runtime.calls.count("quiescent") > 1:
            raise RuntimeError("BACKUP_WRITER_STILL_RUNNING")

    runtime.assert_quiescent = running
    with pytest.raises(ValueError, match="BACKUP_WRITER_STILL_RUNNING"):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    with zipfile.ZipFile(contract["destination"]) as result:
        assert "manifest.json" not in result.namelist()


def test_swapped_target_parent_is_not_followed(creator, contract, tmp_path, monkeypatch):
    target_parent = tmp_path / "target-parent"
    target_parent.mkdir()
    outside = tmp_path / "outside-target"
    outside.mkdir()
    contract["destination"] = str(target_parent / "backup.zip")
    original = creator.inventory_v2

    def changed(source):
        value = original(source)
        target_parent.rename(tmp_path / "former-target-parent")
        target_parent.symlink_to(outside, target_is_directory=True)
        return value

    monkeypatch.setattr(creator, "inventory_v2", changed)
    with pytest.raises(ValueError):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: DatabaseStub())
    assert not (outside / "backup.zip").exists()


def test_primary_failure_survives_maintenance_unlock_error(creator, contract, monkeypatch):
    runtime = DatabaseStub()

    def fail_dump(target, limit):
        raise OSError(errno.ENOSPC, "private path")

    @contextmanager
    def fail_unlock(_):
        try:
            yield
        finally:
            raise OSError(errno.EIO, "private unlock")

    runtime.dump = fail_dump
    monkeypatch.setattr(creator.legacy, "maintenance_lock", fail_unlock)
    with pytest.raises(ValueError) as error:
        creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert error.value.diagnostic["stage"] == "dump_write"
    assert error.value.diagnostic["errno"] == errno.ENOSPC
    assert error.value.diagnostic["cleanup_code"] == "BACKUP_IO_ERROR"
    assert runtime.closed


def test_real_runtime_dump_method_accepts_archive_sink_without_docker(creator, contract):
    from scripts.personal_beta_backup_runtime import DockerBackupRuntime

    adapter = object.__new__(DockerBackupRuntime)
    adapter._exec = lambda: ["synthetic transport"]
    calls = []

    def transport(args, *, sink, limit, timeout):
        calls.append((args, limit, timeout))
        sink.write(b"PGDMP\0real-method-synthetic-transport")
        return b"PGDMP"

    adapter._docker = transport
    runtime = DatabaseStub()
    runtime.dump = lambda target, limit: DockerBackupRuntime.dump(adapter, target, limit)
    creator.create_archive_backup(contract, execute=True, factory=lambda _: runtime)
    assert len(calls) == 1
    assert calls[0][1:] == (64 * 1024**2, 120)


@pytest.mark.parametrize("change", ["append", "hardlink", "rewrite"])
def test_verify_must_leave_sealed_file_identity_unchanged(
    creator, contract, monkeypatch, tmp_path, change
):
    original = creator.archive.verify_stream

    def mutate_after_verify(stream):
        value = original(stream)
        if change == "append":
            with Path(contract["destination"]).open("ab") as changed:
                changed.write(b"tamper")
        elif change == "hardlink":
            os.link(contract["destination"], tmp_path / "unexpected-link")
        else:
            with Path(contract["destination"]).open("r+b") as changed:
                changed.write(b"BAD!")
        return value

    monkeypatch.setattr(creator.archive, "verify_stream", mutate_after_verify)
    with pytest.raises(ValueError, match="BACKUP_TARGET_CHANGED"):
        creator.create_archive_backup(contract, execute=True, factory=lambda _: DatabaseStub())
