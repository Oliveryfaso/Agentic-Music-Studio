"""Synthetic failure diagnostics through the real restore entry points."""

import errno
import json
from pathlib import Path

import pytest
from test_personal_beta_restore import Fake

from scripts import personal_beta_restore as r

PRIVATE = "SYNTHETIC_PRIVATE_DSN_password_path_SQL"
STAGES = {
    "contract",
    "archive_open",
    "archive_verify",
    "child_admission",
    "media_extract",
    "target_readmit",
    "restore_dispatch",
    "dump_copy",
    "pg_restore",
    "db_snapshot",
    "db_compare",
    "archive_close",
    "client_close",
    "device_separation",
    "parent_admission",
    "worker_spawn",
    "worker_wait",
    "target_stop",
    "worker_exit",
    "parent_close",
    "signal_restore",
    "entry",
    "event_transport",
}


def failure_result(invoke):
    with pytest.raises(Exception) as caught:
        invoke()
    error = caught.value
    assert isinstance(error, RuntimeError), (
        "restore failures need one structured RuntimeError boundary"
    )
    assert callable(getattr(error, "as_result", None)), "restore failure lost its diagnostics"
    result = error.as_result()
    assert result["status"] == "FAILED_OR_UNKNOWN"
    assert result["reason"] == "RESTORE_STOPPED"
    assert result["preserve_evidence"] is True
    assert result["first_error"]["stage"] in STAGES
    assert result["first_error"]["error_type"] in {
        "RuntimeError",
        "ValueError",
        "OSError",
        "KeyboardInterrupt",
        "BackupCheckError",
        "BackupRuntimeError",
        "UnknownError",
    }
    assert result["restore_state"] in {"not_started", "unverified", "verified"}
    assert isinstance(result["db_verified"], bool)
    assert isinstance(result["host_child_waited"], bool)
    assert isinstance(result["target_exit_proven"], bool)
    assert result["pg_restore_started"] is None or isinstance(result["pg_restore_started"], bool)
    assert result["pg_restore_cli_exit"] is None or type(result["pg_restore_cli_exit"]) is int
    assert len(result["events"]) <= 48
    assert all(
        event["stage"] in STAGES and event["state"] in {"started", "completed"}
        for event in result["events"]
    )
    assert PRIVATE not in json.dumps(result)
    return result


class PgBoundaryFake(Fake):
    """Replace Docker only, keeping archive reading, extraction, and run real."""

    def __init__(self, *, cli_exit=0, restore_error=None, close_error=None):
        super().__init__()
        self.cli_exit = cli_exit
        self.restore_error = restore_error
        self.close_error = close_error

    def restore(self, dump):
        super().restore(dump)
        diagnostics = getattr(self, "diagnostics", None)
        if diagnostics is not None:
            diagnostics.stage("dump_copy")
            diagnostics.stage("dump_copy", "completed")
            diagnostics.stage("pg_restore")
            diagnostics.pg_restore_started = True
            diagnostics.pg_restore_cli_exit = self.cli_exit
        if self.restore_error is not None:
            raise self.restore_error
        if diagnostics is not None:
            diagnostics.stage("pg_restore", "completed")

    def close(self):
        super().close()
        if self.close_error is not None:
            raise self.close_error


def test_readmission_failure_preserves_extracted_files_without_claiming_restore(case):
    class ReadmitFailure(Fake):
        def admit(self, parent):
            super().admit(parent)
            if self.calls.count("admit") == 2:
                raise RuntimeError("RESTORE_DATABASE_NOT_EMPTY")

    runtime = ReadmitFailure()
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    assert result["first_error"]["stage"] == "target_readmit"
    assert result["first_error"]["error_code"] == "RESTORE_DATABASE_NOT_EMPTY"
    assert result["restore_state"] == "not_started"
    assert result["pg_restore_started"] is False
    assert result["pg_restore_cli_exit"] is None
    assert result["db_verified"] is False
    assert result["host_child_waited"] is False
    assert result["target_exit_proven"] is False
    assert (Path(case["target"]) / "media/audio.wav").read_bytes() == b"synthetic audio"
    assert (Path(case["target"]) / "dump/beta.pgdump").read_bytes().startswith(b"PGDMP")
    assert runtime.closed


def test_pg_restore_failure_survives_client_close_failure(case):
    runtime = PgBoundaryFake(
        cli_exit=3,
        restore_error=RuntimeError("BACKUP_CLI_FAILED"),
        close_error=RuntimeError("BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"),
    )
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    assert result["first_error"]["stage"] == "pg_restore"
    assert result["first_error"]["error_code"] == "BACKUP_CLI_FAILED"
    assert [(error["stage"], error["error_code"]) for error in result["cleanup_errors"]] == [
        ("client_close", "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN")
    ]
    assert result["restore_state"] == "unverified"
    assert result["pg_restore_started"] is True
    assert result["pg_restore_cli_exit"] == 3
    assert result["db_verified"] is False
    assert {"stage": "pg_restore", "state": "started"} in result["events"]
    assert {"stage": "pg_restore", "state": "completed"} not in result["events"]


def test_successful_pg_restore_then_snapshot_failure_remains_unverified(case):
    runtime = PgBoundaryFake()

    def snapshot_failure():
        raise ValueError(PRIVATE)

    runtime.snapshot = snapshot_failure
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    assert result["first_error"]["stage"] == "db_snapshot"
    assert result["first_error"]["error_code"] == "UNKNOWN_EXCEPTION"
    assert result["restore_state"] == "unverified"
    assert result["pg_restore_started"] is True
    assert result["pg_restore_cli_exit"] == 0
    assert result["db_verified"] is False
    assert {"stage": "pg_restore", "state": "completed"} in result["events"]


def test_snapshot_mismatch_is_attributed_to_database_comparison(case):
    runtime = PgBoundaryFake()
    runtime.snapshot = lambda: {"tables": ["changed"], "sequences": []}
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    assert result["first_error"]["stage"] == "db_compare"
    assert result["first_error"]["error_code"] == "RESTORE_DATABASE_MISMATCH"
    assert result["restore_state"] == "unverified"
    assert result["pg_restore_cli_exit"] == 0
    assert result["db_verified"] is False


def test_verified_database_is_retained_when_client_cleanup_fails(case):
    runtime = PgBoundaryFake(close_error=RuntimeError("BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"))
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    assert result["first_error"]["stage"] == "client_close"
    assert result["first_error"]["error_code"] == "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"
    assert result["restore_state"] == "verified"
    assert result["pg_restore_cli_exit"] == 0
    assert result["db_verified"] is True


def test_last_extraction_fsync_failure_is_not_reported_as_pg_restore(case, monkeypatch):
    runtime = Fake()
    fsync = r.os.fsync
    calls = 0

    def last_fsync_fails(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EIO, PRIVATE)
        return fsync(fd)

    monkeypatch.setattr(r.os, "fsync", last_fsync_fails)
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    assert result["first_error"]["stage"] == "media_extract"
    assert result["first_error"]["error_code"] == "UNKNOWN_EXCEPTION"
    assert result["restore_state"] == "not_started"
    assert result["pg_restore_started"] is False
    assert (Path(case["target"]) / "media/audio.wav").read_bytes() == b"synthetic audio"
    assert (Path(case["target"]) / "dump/beta.pgdump").read_bytes().startswith(b"PGDMP")
    assert runtime.closed


def test_main_preserves_structured_failure_without_private_output(case, monkeypatch, capsys):
    runtime = PgBoundaryFake(
        cli_exit=3,
        restore_error=RuntimeError("BACKUP_CLI_FAILED"),
        close_error=RuntimeError(PRIVATE),
    )
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    failure_type = getattr(r, "RestoreFailure", None)
    assert failure_type is not None, "restore needs a serializable failure boundary"

    def failed_supervision(_):
        raise failure_type(result)

    monkeypatch.setattr("sys.argv", ["restore", "--contract", "synthetic", "--execute"])
    monkeypatch.setattr(r.archive.checks, "_manifest", lambda _: {})
    monkeypatch.setattr(r, "supervised", failed_supervision)
    assert r.main() == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == result
    assert PRIVATE not in captured.out


def test_diagnostics_events_are_bounded_and_reject_private_fields():
    diagnostics_type = getattr(r, "Diagnostics", None)
    assert callable(diagnostics_type), "restore needs bounded fixed-stage diagnostics"
    diagnostics = diagnostics_type()
    for _ in range(100):
        diagnostics.stage("archive_verify")
        diagnostics.stage("archive_verify", "completed")
    diagnostics.fail("pg_restore", RuntimeError(PRIVATE))
    diagnostics.cleanup_error("client_close", RuntimeError("BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"))
    result = diagnostics.result()
    assert result["first_error"]["stage"] == "pg_restore"
    assert result["first_error"]["error_code"] == "UNKNOWN_EXCEPTION"
    assert 0 < len(result["events"]) <= 48
    assert all(
        event["stage"] == "archive_verify" and event["state"] in {"started", "completed"}
        for event in result["events"]
    )
    assert result["cleanup_errors"][0]["error_code"] == "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize("failed_phase", ["transfer", "restore"])
def test_actual_restore_method_reports_transfer_vs_restore_cli_failure(case, failed_phase):
    from types import MethodType, SimpleNamespace

    from scripts.personal_beta_backup_runtime import BackupRuntimeError, DockerBackupRuntime

    runtime = Fake()
    runtime.pg = "1" * 64
    runtime.remote_exec_unknown = False
    runtime.cli.children = []
    runtime.cli.close = lambda: None

    def command(argv, **kwargs):
        assert argv[3] == "exec"
        phase = "transfer" if argv[4] == "-i" else "restore"
        if phase == failed_phase:
            runtime.cli.children.append(SimpleNamespace(returncode=3, backup_waited=True))
            raise BackupRuntimeError("BACKUP_CLI_FAILED")
        return b""

    runtime.cli.run = command
    runtime._docker = MethodType(DockerBackupRuntime._docker, runtime)
    runtime._exec = MethodType(DockerBackupRuntime._exec, runtime)
    runtime.restore = MethodType(r.RestoreRuntime.restore, runtime)
    runtime.close = MethodType(DockerBackupRuntime.close, runtime)
    result = failure_result(lambda: r.run(case, True, lambda _: runtime))
    assert result["first_error"]["error_code"] == "BACKUP_CLI_FAILED"
    if failed_phase == "transfer":
        assert result["first_error"]["stage"] == "dump_copy"
        assert result["restore_state"] == "not_started"
        assert result["pg_restore_cli_exit"] is None
    else:
        assert result["first_error"]["stage"] == "pg_restore"
        assert result["restore_state"] == "unverified"
        assert result["pg_restore_cli_exit"] == 3
        assert result["cleanup_errors"][0]["error_code"] == "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"
