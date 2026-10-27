"""Real supervisor and child entry points with synthetic process/PG boundaries."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_restore_failure_diagnostics import PgBoundaryFake

from scripts import personal_beta_restore as r

PRIVATE = "SYNTHETIC_PRIVATE_PIPE_MESSAGE"


@pytest.fixture
def supervise_boundaries(monkeypatch):
    def install(frames, *, stop_error=None, exitcode=0):
        clock = [0.0]

        class Parent:
            def __init__(self, contract):
                self.container_deadline = 900

            def admit(self, parent):
                pass

            def close(self):
                pass

        class Pipe:
            def __init__(self, messages):
                self.messages = list(messages)

            def poll(self, timeout):
                clock[0] += timeout
                return bool(self.messages)

            def recv(self):
                message = self.messages.pop(0)
                if isinstance(message, BaseException):
                    raise message
                return message

            def close(self):
                pass

        class Child:
            pid = 123

            def __init__(self):
                self.exitcode = exitcode

            def start(self):
                pass

            def is_alive(self):
                return False

            def join(self, timeout):
                pass

        receiver, sender = Pipe(frames), Pipe([])
        child = Child()
        context = SimpleNamespace(Pipe=lambda **_: (receiver, sender), Process=lambda **_: child)

        def stop(parent):
            if stop_error is not None:
                raise stop_error

        monkeypatch.setattr(r, "validate", lambda _: Path("/synthetic/restore"))
        monkeypatch.setattr(r, "RestoreRuntime", Parent)
        monkeypatch.setattr(r.multiprocessing, "get_context", lambda _: context)
        monkeypatch.setattr(r.time, "monotonic", lambda: clock[0])
        monkeypatch.setattr(r.signal, "signal", lambda *_: None)
        monkeypatch.setattr(r, "stop_proven_target", stop)

    return install


def child_snapshot_frames(*, verified=False, failed=False, terminal=True):
    frames = []
    child = r.Diagnostics(observer=frames.append)
    child.stage("dump_copy")
    child.stage("dump_copy", "completed")
    child.pg_restore_started = True
    child.stage("pg_restore")
    child.pg_restore_cli_exit = 0
    child.stage("pg_restore", "completed")
    child.stage("db_snapshot")
    if verified:
        child.stage("db_snapshot", "completed")
        child.stage("db_compare")
        child.db_verified = True
        child.stage("db_compare", "completed")
    if failed:
        child.fail("db_snapshot", RuntimeError("BACKUP_CLI_FAILED"))
    if terminal:
        frames.append({"kind": "result", "result": child.result(success=verified)})
    return frames


def supervision_failure():
    with pytest.raises(r.RestoreFailure) as caught:
        r.supervised({"archive": "/synthetic/archive"})
    result = caught.value.as_result()
    assert result["status"] == "FAILED_OR_UNKNOWN"
    assert result["preserve_evidence"] is True
    assert PRIVATE not in json.dumps(result)
    return result


def test_streamed_snapshot_first_error_survives_parent_stop_failure(supervise_boundaries):
    frames = child_snapshot_frames(failed=True)
    supervise_boundaries(frames, stop_error=RuntimeError("RESTORE_STOP_IDENTITY"))
    result = supervision_failure()
    assert result["first_error"] == {
        "stage": "db_snapshot",
        "error_code": "BACKUP_CLI_FAILED",
        "error_type": "RuntimeError",
    }
    assert [(error["stage"], error["error_code"]) for error in result["cleanup_errors"]] == [
        ("target_stop", "RESTORE_STOP_IDENTITY")
    ]
    assert result["pg_restore_started"] is True
    assert result["pg_restore_cli_exit"] == 0
    assert result["restore_state"] == "unverified"
    assert result["db_verified"] is False
    assert result["host_child_waited"] is True
    assert result["target_exit_proven"] is False
    assert {"stage": "db_snapshot", "state": "started"} in result["events"]


@pytest.mark.parametrize("lost_pipe", [False, True], ids=["missing-terminal", "pipe-eof"])
def test_missing_terminal_retains_last_child_stage_and_cannot_pass(supervise_boundaries, lost_pipe):
    frames = child_snapshot_frames(terminal=False)
    if lost_pipe:
        frames.append(EOFError(PRIVATE))
    supervise_boundaries(frames)
    result = supervision_failure()
    assert result["first_error"]["stage"] == "worker_wait"
    assert result["first_error"]["error_code"] in {"RESTORE_WORKER_UNKNOWN", "UNKNOWN_EXCEPTION"}
    assert result["pg_restore_started"] is True
    assert result["pg_restore_cli_exit"] == 0
    assert result["restore_state"] == "unverified"
    assert result["db_verified"] is False
    assert result["host_child_waited"] is True
    assert result["target_exit_proven"] is True
    assert {"stage": "db_snapshot", "state": "started"} in result["events"]
    assert {"stage": "db_snapshot", "state": "completed"} not in result["events"]


def test_stop_failure_keeps_verified_child_database_but_fails_overall(supervise_boundaries):
    supervise_boundaries(
        child_snapshot_frames(verified=True), stop_error=RuntimeError("RESTORE_TARGET_EXIT_UNKNOWN")
    )
    result = supervision_failure()
    assert result["first_error"]["stage"] == "target_stop"
    assert result["first_error"]["error_code"] == "RESTORE_TARGET_EXIT_UNKNOWN"
    assert result["restore_state"] == "verified"
    assert result["db_verified"] is True
    assert result["pg_restore_cli_exit"] == 0
    assert result["host_child_waited"] is True
    assert result["target_exit_proven"] is False


def test_verified_terminal_cannot_pass_without_proven_host_child_exit(supervise_boundaries):
    supervise_boundaries(child_snapshot_frames(verified=True), exitcode=None)
    result = supervision_failure()
    assert result["first_error"]["stage"] == "worker_wait"
    assert result["first_error"]["error_code"] == "RESTORE_WORKER_UNKNOWN"
    assert result["db_verified"] is True
    assert result["restore_state"] == "verified"
    assert result["host_child_waited"] is False
    assert result["target_exit_proven"] is True


def test_child_serializes_real_run_failure_without_duplicating_cleanup(case, monkeypatch):
    runtime = PgBoundaryFake(
        cli_exit=3,
        restore_error=RuntimeError("BACKUP_CLI_FAILED"),
        close_error=RuntimeError("BACKUP_REMOTE_EXEC_EXIT_UNKNOWN"),
    )
    # Change only the runtime factory default; the child still executes the real run body.
    monkeypatch.setattr(r.run, "__defaults__", (False, lambda _: runtime, None))
    monkeypatch.setattr(r.signal, "signal", lambda *_: None)
    monkeypatch.setattr(
        r,
        "os",
        SimpleNamespace(
            stat=lambda path: SimpleNamespace(st_dev=1 if str(path) == case["archive"] else 2),
            fstat=r.os.fstat,
            statvfs=r.os.statvfs,
            fsync=r.os.fsync,
        ),
    )
    frames = []
    pipe = SimpleNamespace(send=frames.append, close=lambda: None)
    r._restore_child(case, pipe)
    terminals = [frame["result"] for frame in frames if frame["kind"] == "result"]
    assert len(terminals) == 1
    result = terminals[0]
    assert result["first_error"]["stage"] == "pg_restore"
    assert result["first_error"]["error_code"] == "BACKUP_CLI_FAILED"
    assert result["pg_restore_cli_exit"] == 3
    assert result["restore_state"] == "unverified"
    assert [(error["stage"], error["error_code"]) for error in result["cleanup_errors"]] == [
        ("client_close", "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN")
    ]
    assert runtime.closed
