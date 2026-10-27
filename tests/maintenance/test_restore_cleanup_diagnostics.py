"""Cleanup still runs, and cleanup errors cannot replace the first failure."""

import json
from types import SimpleNamespace

import pytest
from test_restore_supervision_diagnostics import child_snapshot_frames

from scripts import personal_beta_restore as r

PRIVATE = "SYNTHETIC_PRIVATE_CLEANUP_DETAIL"


def test_broken_event_pipe_does_not_prevent_cleanup_action():
    def broken_pipe(frame):
        raise BrokenPipeError(PRIVATE)

    closed = []
    diagnostics = r.Diagnostics(observer=broken_pipe)
    diagnostics.cleanup("client_close", lambda: closed.append(True))
    assert closed == [True], "event delivery must not skip the actual client close/wait"
    result = diagnostics.result()
    assert result["first_error"] == {
        "stage": "event_transport",
        "error_code": "RESTORE_EVENT_PIPE_UNKNOWN",
        "error_type": "RuntimeError",
    }
    assert result["status"] == "FAILED_OR_UNKNOWN"
    assert PRIVATE not in json.dumps(result)


def test_receiver_close_failure_preserves_child_error_and_finishes_parent_cleanup(
    supervise_boundaries, monkeypatch
):
    supervise_boundaries(child_snapshot_frames(failed=True))
    context = r.multiprocessing.get_context("spawn")
    receiver, _ = context.Pipe(duplex=False)
    parent_closed = []
    handlers = []
    old_handler = object()

    def broken_close():
        raise OSError(PRIVATE)

    def set_handler(signum, handler):
        handlers.append(handler)
        return old_handler

    monkeypatch.setattr(receiver, "close", broken_close)
    monkeypatch.setattr(r.RestoreRuntime, "close", lambda _: parent_closed.append(True))
    monkeypatch.setattr(r.signal, "signal", set_handler)
    with pytest.raises(Exception) as caught:
        r.supervised({"archive": "/synthetic/archive"})
    assert parent_closed == [True], "pipe close must not skip the parent's client close"
    assert handlers[-1] is old_handler, "pipe close must not skip restoring the signal handler"
    assert isinstance(caught.value, r.RestoreFailure), (
        "pipe close erased the structured child failure"
    )
    result = caught.value.as_result()
    assert result["first_error"] == {
        "stage": "db_snapshot",
        "error_code": "BACKUP_CLI_FAILED",
        "error_type": "RuntimeError",
    }
    assert any(error["error_code"] == "UNKNOWN_EXCEPTION" for error in result["cleanup_errors"])
    assert result["pg_restore_cli_exit"] == 0
    assert result["restore_state"] == "unverified"
    assert PRIVATE not in json.dumps(result)


def test_stop_identity_failure_survives_its_cli_close_failure(monkeypatch):
    pg = "1" * 64
    runtime = SimpleNamespace(
        pg=pg,
        contract={"daemon_id": "synthetic", "owner": "a" * 32},
        proof=(pg, "sha256:" + "2" * 64, "synthetic-created"),
    )

    class CLI:
        def run(self, args, **kwargs):
            command = args[3:]
            if command == ["info", "--format", "{{.ID}}"]:
                return b"synthetic"
            if command == ["inspect", pg]:
                return json.dumps(
                    [
                        {
                            "Id": pg,
                            "Image": "sha256:" + "3" * 64,
                            "Created": "synthetic-created",
                            "Config": {"Labels": {"io.motif.restore.owner": "a" * 32}},
                            "Mounts": [],
                            "State": {"Running": True, "Pid": 1},
                        }
                    ]
                ).encode()
            pytest.fail("identity failure must stop admission before lifecycle commands")

        def close(self):
            raise RuntimeError("BACKUP_CLI_EXIT_UNKNOWN")

    monkeypatch.setattr(r, "_OwnedCLI", CLI)
    with pytest.raises(Exception) as caught:
        r.stop_proven_target(runtime)
    assert isinstance(caught.value, r.RestoreFailure), (
        "stop cleanup erased the first admission failure"
    )
    result = caught.value.as_result()
    assert result["first_error"]["error_code"] == "RESTORE_STOP_IDENTITY"
    assert [error["error_code"] for error in result["cleanup_errors"]] == [
        "BACKUP_CLI_EXIT_UNKNOWN"
    ]
    assert result["status"] == "FAILED_OR_UNKNOWN"
    assert result["target_exit_proven"] is False
