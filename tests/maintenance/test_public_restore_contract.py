"""Portable restore contracts bind the caller's archive hash before any work."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_personal_beta_restore import Fake

from scripts import personal_beta_restore as r


@pytest.fixture
def public_contract(tmp_path):
    return {
        "archive": str(tmp_path / "absent-synthetic.zip"),
        "archive_root": str(tmp_path),
        "archive_sha256": "a" * 64,
        "target": str(tmp_path / "restored"),
        "target_root": str(tmp_path),
        "owner": "a" * 32,
        "daemon_id": "synthetic",
        "pg_id": "1" * 64,
        "pg_image": "sha256:" + "2" * 64,
        "expected_db_revision": r.REVISION,
    }


def test_public_restore_has_no_global_personal_archive_pin():
    assert not hasattr(r, "PIN")


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("missing", None, "RESTORE_CONTRACT_FIELDS"),
        ("bad-type", None, "RESTORE_ARCHIVE_PIN_INVALID"),
        ("uppercase", "A" * 64, "RESTORE_ARCHIVE_PIN_INVALID"),
        ("wrong-length", "a" * 63, "RESTORE_ARCHIVE_PIN_INVALID"),
    ],
)
def test_hash_rejected_before_runtime_or_archive_access(
    public_contract, monkeypatch, kind, value, expected
):
    if kind == "missing":
        public_contract.pop("archive_sha256")
    else:
        public_contract["archive_sha256"] = value
    touched = []

    def runtime_factory(_):
        touched.append("runtime")
        raise AssertionError("invalid contract constructed a runtime")

    def archive_reader(*args):
        touched.append("archive")
        raise AssertionError("invalid contract read an archive")

    monkeypatch.setattr(r.archive, "_locked_archive", archive_reader)
    with pytest.raises(r.RestoreFailure) as caught:
        r.run(public_contract, True, runtime_factory)
    assert touched == []
    first = caught.value.as_result()["first_error"]
    assert first["stage"] == "contract"
    assert first["error_code"] == expected
    assert not Path(public_contract["target"]).exists()


def test_valid_caller_hash_dry_run_needs_no_archive_runtime_or_target(public_contract, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry run performed archive or runtime work")

    monkeypatch.setattr(r.archive, "_locked_archive", forbidden)
    result = r.run(public_contract, factory=forbidden)
    assert result == {"status": "DRY_RUN", "restore_performed": False, "runtime_verified": False}
    assert not Path(public_contract["archive"]).exists()
    assert not Path(public_contract["target"]).exists()


def test_real_synthetic_archive_must_match_the_contract_hash(case):
    case["archive_sha256"] = "0" * 64
    runtime = Fake()
    with pytest.raises(r.RestoreFailure) as caught:
        r.run(case, True, lambda _: runtime)
    result = caught.value.as_result()
    assert result["first_error"]["stage"] == "archive_verify"
    assert result["first_error"]["error_code"] == "RESTORE_ARCHIVE_PIN"
    assert result["restore_state"] == "not_started"
    assert runtime.calls == []
    assert runtime.closed
    assert not Path(case["target"]).exists()


def test_import_and_help_do_not_spawn_connect_or_create_resources(tmp_path):
    root = Path(__file__).resolve().parents[2]
    guarded_entry = """
import importlib,os,runpy,sys
def guard(event,args):
    if event.startswith(('subprocess.','socket.')) or event in {
        'os.system','os.posix_spawn','os.mkdir','os.remove','os.rename','os.rmdir',
        'os.link','os.symlink','os.truncate','os.chmod','os.chown','os.fork',
    }:
        raise AssertionError('maintenance entry attempted a side effect')
    if event == 'open':
        mode,flags=args[1],args[2]
        writes = os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags,int) and flags & writes
        ):
            raise AssertionError('maintenance entry attempted a file write')
sys.addaudithook(guard)
if sys.argv[1] == 'import':
    importlib.import_module('scripts.personal_beta_restore')
    print('IMPORT_OK')
else:
    sys.argv=['personal_beta_restore','--help']
    runpy.run_module('scripts.personal_beta_restore',run_name='__main__')
"""
    environment = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    for mode in ("import", "help"):
        result = subprocess.run(
            [sys.executable, "-B", "-c", guarded_entry, mode],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()
        assert result.stderr == b""
        if mode == "import":
            assert result.stdout == b"IMPORT_OK\n"
        else:
            assert b"--contract" in result.stdout and b"--execute" in result.stdout
    assert list(tmp_path.iterdir()) == []
