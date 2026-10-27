"""Synthetic directories and an explicit DB boundary stub; no Docker or user data."""

import errno
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import personal_beta_backup as legacy


def test_explicit_create_entry_exists():
    assert importlib.util.find_spec("scripts.personal_beta_backup_create") is not None


@pytest.fixture
def creator():
    try:
        return importlib.import_module("scripts.personal_beta_backup_create")
    except ModuleNotFoundError:
        pytest.fail("explicit application backup creation entry is missing")


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "audio.wav").write_bytes(b"synthetic audio bytes")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (runtime / "operation.lock").touch(mode=0o600)
    owner = "11111111-1111-4111-8111-111111111111"
    record = {
        "schema": "motif-owned-stack.v1",
        "project_root": str(tmp_path),
        "compose_project": "motif-test",
        "daemon_id": "test-daemon",
        "owner": owner,
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
    contract = {
        "schema": "motif-beta-backup-create.v1",
        "allowed_root": str(tmp_path),
        "source": str(source),
        "destination": str(tmp_path / "backup"),
        "runtime_dir": str(runtime),
        **{k: record[k] for k in record if k != "schema"},
        "containers": {s: f"{i:064x}" for i, s in enumerate(roles, 1)},
        "images": {s: "sha256:" + f"{i:064x}" for i, s in enumerate(roles, 1)},
        "expected_db_revision": "20261020_0030",
    }
    return contract


class DatabaseStub:
    def __init__(self, contract):
        self.contract, self.calls, self.closed = contract, [], False
        self.changed, self.running_writer, self.fail_dump = False, False, False

    def assert_quiescent(self):
        self.calls.append("quiescent")
        if self.running_writer:
            raise ValueError("WRITER_STILL_RUNNING")

    def snapshot(self):
        self.calls.append("snapshot")
        return {
            "database": "motif_forge",
            "schema_revision": "20261020_0030",
            "tables": [
                {
                    "schema": "app",
                    "table": "synthetic",
                    "rows": 1,
                    "digest": "changed" if self.changed else "stable",
                }
            ],
            "sequences": [],
        }

    def dump(self, target, max_bytes):
        self.calls.append("dump")
        assert max_bytes == 64 * 1024**2
        if self.fail_dump:
            raise ValueError("DUMP_FAILED")
        target.write(b"PGDMP\x00synthetic-boundary-only")

    def close(self):
        self.closed = True


def test_default_dry_run_does_not_construct_runtime_or_write(creator, setup):
    before = sorted(str(p) for p in Path(setup["allowed_root"]).rglob("*"))
    result = creator.create_backup(setup, factory=lambda _: pytest.fail("dryrun called Docker"))
    assert result["backup_performed"] is False and result["status"] == "backup_plan_only"
    assert sorted(str(p) for p in Path(setup["allowed_root"]).rglob("*")) == before


def test_explicit_create_reuses_old_verifier_and_keeps_restore_unproven(creator, setup):
    runtime = DatabaseStub(setup)
    result = creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    backup = Path(setup["destination"])
    assert result["backup_performed"] is True
    assert result["database_restore_tested"] is False
    assert result["consistency_boundary"] == "cooperative_single_host_maintenance"
    assert legacy.verify_backup(backup, Path(setup["allowed_root"]))["integrity"] == "verified"
    assert runtime.closed
    assert (backup / "artifacts/audio.wav").read_bytes() == b"synthetic audio bytes"
    assert [p.name for p in backup.iterdir()].count("manifest.json") == 1


def test_cli_create_defaults_to_dryrun(creator, setup, tmp_path, capsys):
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(setup))
    assert legacy.main(["create", "--contract", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["backup_performed"] is False
    assert not Path(setup["destination"]).exists()


@pytest.mark.parametrize(
    "change", ["existing", "inside_source", "symlink", "outside", "parent_absent"]
)
def test_path_rejection_precedes_runtime(creator, setup, tmp_path, change):
    dest = Path(setup["destination"])
    if change == "existing":
        dest.mkdir()
        (dest / "sentinel").write_text("keep")
    elif change == "inside_source":
        setup["destination"] = str(Path(setup["source"]) / "backup")
    elif change == "symlink":
        dest.symlink_to(Path(setup["source"]))
    elif change == "outside":
        setup["destination"] = str(tmp_path.parent / "foreign")
    else:
        setup["destination"] = str(tmp_path / "missing" / "backup")
    with pytest.raises(ValueError):
        creator.create_backup(
            setup, execute=True, factory=lambda _: pytest.fail("invalid path ran")
        )
    if change == "existing":
        assert (dest / "sentinel").read_text() == "keep"


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_db_revision", "20261024_0031"),
        ("owner", "bad"),
        ("daemon_id", ""),
        ("source", "relative"),
        ("schema", "v0"),
    ],
)
def test_contract_rejects_unsupported_or_unbound_identity(creator, setup, field, value):
    setup[field] = value
    with pytest.raises(ValueError):
        creator.create_backup(setup)


def test_same_runtime_lock_blocks_create(creator, setup):
    import fcntl

    with (Path(setup["runtime_dir"]) / "operation.lock").open("r+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="BUSY"):
            creator.create_backup(
                setup, execute=True, factory=lambda _: pytest.fail("lock bypassed")
            )
    assert not Path(setup["destination"]).exists()


def test_running_writer_refuses_before_reading_media_or_creating_target(creator, setup):
    runtime = DatabaseStub(setup)
    runtime.running_writer = True
    with pytest.raises(ValueError):
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    assert runtime.closed and not Path(setup["destination"]).exists()


@pytest.mark.parametrize("kind", ["symlink", "fifo", "extra_metadata"])
def test_invalid_media_inventory_rejected_before_dump(creator, setup, kind):
    source = Path(setup["source"])
    if kind == "symlink":
        (source / "link").symlink_to(source / "audio.wav")
    elif kind == "fifo":
        os.mkfifo(source / "pipe")
    else:
        (source / "._audio.wav").write_bytes(b"fake metadata")
    runtime = DatabaseStub(setup)
    with pytest.raises(ValueError):
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    assert "dump" not in runtime.calls and runtime.closed
    assert (source / "audio.wav").read_bytes() == b"synthetic audio bytes"


def test_dump_failure_preserves_source_and_partial_without_complete_manifest(creator, setup):
    runtime = DatabaseStub(setup)
    runtime.fail_dump = True
    with pytest.raises(ValueError):
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    assert runtime.closed and not (Path(setup["destination"]) / "manifest.json").exists()
    assert (Path(setup["source"]) / "audio.wav").read_bytes() == b"synthetic audio bytes"


@pytest.mark.parametrize("changed", ["database", "media", "extra_file", "writer"])
def test_change_during_dump_cannot_publish_complete_manifest(creator, setup, changed):
    runtime = DatabaseStub(setup)
    original = runtime.dump

    def mutate(target, max_bytes):
        original(target, max_bytes)
        if changed == "database":
            runtime.changed = True
        elif changed == "media":
            (Path(setup["source"]) / "audio.wav").write_bytes(b"changed")
        elif changed == "extra_file":
            (Path(setup["source"]) / "late.wav").write_bytes(b"late")
        else:
            runtime.running_writer = True

    runtime.dump = mutate
    with pytest.raises(ValueError):
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    assert runtime.closed and not (Path(setup["destination"]) / "manifest.json").exists()


def test_manifest_contains_table_digests_and_all_file_checksums(creator, setup):
    creator.create_backup(setup, execute=True, factory=DatabaseStub)
    manifest = json.loads((Path(setup["destination"]) / "manifest.json").read_text())
    row = manifest["files"][0]
    assert row["sha256"] == hashlib.sha256(b"synthetic audio bytes").hexdigest()
    assert manifest["db_tables"][0]["table"] == "synthetic"
    assert manifest["schema_revision"] == "20261020_0030"
    assert manifest["database_restore_tested"] is False


def test_appledouble_for_empty_directory_keeps_required_companion(creator, setup):
    source = Path(setup["source"])
    (source / "empty").mkdir()
    payload = bytes.fromhex("0005160700020000") + bytes(18)
    (source / "._empty").write_bytes(payload)
    creator.create_backup(setup, execute=True, factory=DatabaseStub)
    backup = Path(setup["destination"])
    assert (backup / "artifacts/empty").is_dir()
    assert (backup / "artifacts/._empty").read_bytes() == payload
    assert legacy.verify_backup(backup, Path(setup["allowed_root"]))["platform_metadata_files"] == 1


def test_metadata_companion_cannot_escape_artifact_root(creator, setup):
    source = Path(setup["source"])
    (source / "._..").write_bytes(bytes.fromhex("0005160700020000") + bytes(18))
    runtime = DatabaseStub(setup)
    with pytest.raises(ValueError):
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    assert "dump" not in runtime.calls


def test_unreadable_source_subtree_cannot_be_silently_omitted(creator, setup, monkeypatch):
    source = Path(setup["source"])
    hidden = source / "unreadable"
    hidden.mkdir()
    (hidden / "keep.wav").write_bytes(b"must not disappear")
    original = os.scandir

    def denied(path):
        if Path(path) == hidden:
            raise PermissionError("synthetic-private-path")
        return original(path)

    monkeypatch.setattr(os, "scandir", denied)
    runtime = DatabaseStub(setup)
    with pytest.raises(ValueError, match="WALK"):
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    assert "dump" not in runtime.calls
    assert not (Path(setup["destination"]) / "manifest.json").exists()


def test_cli_keeps_only_controlled_runtime_error_codes(
    creator, setup, tmp_path, monkeypatch, capsys
):
    from scripts.personal_beta_backup_runtime import BackupRuntimeError

    path = tmp_path / "contract.json"
    path.write_text(json.dumps(setup))

    def rejected(*_args, **_kwargs):
        raise BackupRuntimeError("BACKUP_WRITER_STILL_RUNNING")

    monkeypatch.setattr(creator, "create_backup", rejected)
    assert legacy.main(["create", "--contract", str(path), "--execute"]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "BACKUP_WRITER_STILL_RUNNING"}


def test_real_script_cli_retains_creation_validation_code(setup, tmp_path):
    path = tmp_path / "contract.json"
    setup["expected_db_revision"] = "unsupported"
    path.write_text(json.dumps(setup))
    result = subprocess.run(
        [sys.executable, "-B", str(Path(legacy.__file__)), "create", "--contract", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"error": "BACKUP_SCHEMA_UNSUPPORTED"}
    assert result.stderr == ""


def test_controlled_exception_cannot_echo_arbitrary_text(
    creator, setup, tmp_path, monkeypatch, capsys
):
    from scripts.personal_beta_backup_runtime import BackupRuntimeError

    path = tmp_path / "contract.json"
    path.write_text(json.dumps(setup))

    def rejected(*_args, **_kwargs):
        raise BackupRuntimeError("synthetic/private/path")

    monkeypatch.setattr(creator, "create_backup", rejected)
    assert legacy.main(["create", "--contract", str(path), "--execute"]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "BACKUP_RUNTIME_FAILED"}


def test_dump_io_error_has_safe_stage_errno_and_preserves_first_error(creator, setup):
    runtime = DatabaseStub(setup)

    def fail_dump(*_args):
        raise OSError(errno.ENOSPC, "synthetic-secret", "/private/sensitive-source")

    def fail_close():
        raise RuntimeError("BACKUP_REMOTE_EXEC_EXIT_UNKNOWN")

    runtime.dump, runtime.close = fail_dump, fail_close
    with pytest.raises(ValueError) as caught:
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    error = caught.value
    assert str(error) == "BACKUP_IO_ERROR"
    assert error.diagnostic["stage"] == "dump_write"
    assert error.diagnostic["errno"] == errno.ENOSPC
    assert error.diagnostic["cleanup_code"] == "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"
    assert "synthetic-secret" not in str(error) + repr(error.diagnostic)
    assert "/private/" not in str(error) + repr(error.diagnostic)


def test_real_cli_io_error_has_diagnostic_without_private_path(setup, tmp_path):
    (Path(setup["runtime_dir"]) / "operation.lock").unlink()
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(setup))
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(legacy.__file__)),
            "create",
            "--contract",
            str(path),
            "--execute",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["error"] == "BACKUP_IO_ERROR"
    assert output["diagnostic"]["stage"] == "maintenance_lock"
    assert output["diagnostic"]["errno"] == errno.ENOENT
    assert result.stderr == ""
    assert str(tmp_path) not in result.stdout


def test_runtime_close_first_error_survives_later_lock_release_error(creator, setup, monkeypatch):
    runtime = DatabaseStub(setup)

    def fail_close():
        raise RuntimeError("BACKUP_REMOTE_EXEC_EXIT_UNKNOWN")

    original = creator.fcntl.flock

    def unlock_fails(fd, operation):
        if operation == creator.fcntl.LOCK_UN:
            raise OSError(errno.EIO, "synthetic-private-lock")
        return original(fd, operation)

    runtime.close = fail_close
    monkeypatch.setattr(creator.fcntl, "flock", unlock_fails)
    with pytest.raises(ValueError) as caught:
        creator.create_backup(setup, execute=True, factory=lambda _: runtime)
    assert str(caught.value) == "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"
    assert caught.value.diagnostic["stage"] == "runtime_close"
    assert caught.value.diagnostic["cleanup_code"] == "BACKUP_IO_ERROR"
