"""Public format selection stays explicit; restore remains read-only."""

import json
import os
import subprocess
import sys
from pathlib import Path

from test_personal_beta_backup_create import DatabaseStub, setup  # noqa: F401

from scripts import personal_beta_backup as entry


def test_archive_format_is_explicit_and_cli_defaults_to_no_execution(setup, tmp_path):  # noqa: F811
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(setup))
    before = set(tmp_path.rglob("*"))
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            entry.__file__,
            "create",
            "--contract",
            str(contract_path),
            "--format",
            "archive-v2",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["backup_performed"] is False
    assert set(tmp_path.rglob("*")) == before


def test_v2_public_verify_and_restore_plan_keep_real_dot_underscore_files(setup, tmp_path):  # noqa: F811
    from scripts.personal_beta_backup_archive_create import create_archive_backup

    source = Path(setup["source"])
    (source / "._real-user-file").write_bytes(b"ordinary user bytes")
    (source / "empty").mkdir()
    setup["destination"] = str(tmp_path / "backup.motif.zip")
    runtime = DatabaseStub(setup)
    result = create_archive_backup(setup, execute=True, factory=lambda _: runtime)
    assert result["backup_performed"] is True
    assert runtime.closed
    backup = Path(setup["destination"])
    assert entry.verify_backup(backup, tmp_path)["integrity"] == "verified"
    restore_target = tmp_path / "independent-restore"
    result = entry.plan_restore(backup, restore_target, tmp_path)
    assert result["restore_performed"] is False
    assert result["ready_for_real_restore"] is False
    assert not restore_target.exists()
    for command in (
        ["verify"],
        ["restore", "--target", str(restore_target), "--dry-run"],
    ):
        response = subprocess.run(
            [
                sys.executable,
                "-B",
                entry.__file__,
                *command,
                "--backup",
                str(backup),
                "--allowed-root",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert response.returncode == 0, response.stderr
        assert json.loads(response.stdout)["integrity"] == "verified"
        assert response.stderr == ""
    assert not restore_target.exists()
