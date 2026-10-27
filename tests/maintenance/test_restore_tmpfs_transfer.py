"""Real restore command construction; Docker boundary only is simulated."""

from types import MethodType

import pytest

from scripts.personal_beta_backup_runtime import BackupRuntimeError, DockerBackupRuntime
from scripts.personal_beta_restore import RestoreRuntime
from scripts.restore_diagnostics import Diagnostics


class CopyBoundary:
    def __init__(self, fail_transfer=False):
        self.children = []
        self.calls = []
        self.received = None
        self.fail_transfer = fail_transfer

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[3] == "cp":
            raise BackupRuntimeError("BACKUP_CLI_FAILED")
        if argv[3:5] == ["exec", "-i"]:
            if self.fail_transfer:
                raise BackupRuntimeError("BACKUP_CLI_FAILED")
            self.received = kwargs["stdin_file"].read()
        return b""


def runtime(boundary):
    obj = RestoreRuntime.__new__(RestoreRuntime)
    obj.pg = "1" * 64
    obj.remote_exec_unknown = False
    obj.cli = boundary
    obj.diagnostics = Diagnostics()
    obj._exec = MethodType(DockerBackupRuntime._exec, obj)
    obj._docker = MethodType(DockerBackupRuntime._docker, obj)
    return obj


def test_restore_transfers_exact_dump_inside_tmpfs_without_daemon_cp(tmp_path):
    payload = b"PGDMP\x00\x01\x80synthetic\n"
    dump = tmp_path / "dump with spaces.pgdump"
    dump.write_bytes(payload)
    boundary = CopyBoundary()
    obj = runtime(boundary)
    obj.restore(dump)
    assert boundary.received == payload
    assert len(boundary.calls) == 2
    transfer, kwargs = boundary.calls[0]
    assert transfer[:6] == ["docker", "--context", "colima", "exec", "-i", "--user"]
    assert transfer[6:8] == ["postgres", obj.pg]
    assert transfer[-3:] == ["/bin/sh", "-c", "umask 077; set -C; cat > /tmp/restore.pgdump"]
    assert kwargs["stdin_file"].closed
    restore, _ = boundary.calls[1]
    assert restore[-1] == "/tmp/restore.pgdump"
    assert "--single-transaction" in restore and "--exit-on-error" in restore
    assert "--no-owner" in restore and "--no-privileges" in restore
    assert not any(arg.startswith("PGOPTIONS=") for arg in restore)
    assert obj.diagnostics.pg_restore_started


def test_transfer_failure_never_starts_pg_restore(tmp_path):
    dump = tmp_path / "dump.pgdump"
    dump.write_bytes(b"PGDMPsynthetic")
    boundary = CopyBoundary(fail_transfer=True)
    obj = runtime(boundary)
    with pytest.raises(BackupRuntimeError):
        obj.restore(dump)
    assert len(boundary.calls) == 1
    assert not obj.diagnostics.pg_restore_started
    assert obj.remote_exec_unknown


def test_dump_input_symlink_is_rejected_before_any_docker_command(tmp_path):
    actual = tmp_path / "actual"
    actual.write_bytes(b"PGDMPsynthetic")
    link = tmp_path / "link"
    link.symlink_to(actual)
    boundary = CopyBoundary()
    with pytest.raises(BackupRuntimeError, match="BACKUP_STDIN_INVALID"):
        runtime(boundary).restore(link)
    assert not boundary.calls
