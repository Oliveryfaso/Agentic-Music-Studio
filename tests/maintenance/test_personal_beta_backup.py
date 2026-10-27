"""Synthetic files only; no real backup, database, Docker or service access."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts.personal_beta_backup import (
    BackupCheckError,
    main,
    plan_backup,
    plan_restore,
    verify_backup,
)


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    source = root / "source"
    source.mkdir()
    backup = root / "backup"
    (backup / "artifacts").mkdir(parents=True)
    blob = b"synthetic audio"
    (backup / "artifacts/payload.wav").write_bytes(blob)
    dump = b"synthetic dump; no database was queried"
    (backup / "beta.pgdump").write_bytes(dump)
    manifest = {
        "source_root": str(source),
        "files": [
            {"path": "payload.wav", "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
        ],
        "db_dump": {
            "path": "beta.pgdump",
            "bytes": len(dump),
            "sha256": hashlib.sha256(dump).hexdigest(),
        },
        "platform_metadata": [],
        "db_tables": [{"schema": "public", "table": "synthetic"}],
    }
    (backup / "manifest.json").write_text(json.dumps(manifest))
    return root, source, backup, manifest


def test_verify_does_not_claim_database_artifact_consistency(bundle):
    root, _, backup, _ = bundle
    result = verify_backup(backup, root)
    assert result["integrity"] == "verified"
    assert result["artifact_files"] == 1
    assert result["db_artifact_consistency"] == "not_proven_by_integrity_check"
    assert result["database_restore_tested"] is False


@pytest.mark.parametrize(
    "version", ["motif-beta-maintenance-backup.v999", "motif-beta-maintenance-backup.v2", None]
)
def test_directory_reader_rejects_explicit_unknown_or_archive_version(bundle, version):
    root, _, backup, manifest = bundle
    manifest["schema_version"] = version
    (backup / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BackupCheckError, match="BACKUP_SCHEMA_UNSUPPORTED"):
        verify_backup(backup, root)


def test_directory_reader_keeps_explicit_v1_compatibility(bundle):
    root, _, backup, manifest = bundle
    manifest["schema_version"] = "motif-beta-maintenance-backup.v1"
    (backup / "manifest.json").write_text(json.dumps(manifest))
    assert verify_backup(backup, root)["integrity"] == "verified"


def test_unreadable_unknown_backup_subtree_is_not_ignored(bundle, monkeypatch):
    root, _, backup, _ = bundle
    hidden = backup / "unreadable"
    hidden.mkdir()
    (hidden / "unlisted").write_bytes(b"must reject")
    original = os.scandir

    def denied(path):
        if Path(path) == hidden:
            raise PermissionError("synthetic-private-path")
        return original(path)

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(BackupCheckError, match="WALK"):
        verify_backup(backup, root)


@pytest.mark.parametrize("fault", ["missing", "changed", "extra", "symlink", "dump_missing"])
def test_verify_rejects_damaged_or_unlisted_content(bundle, fault):
    root, _, backup, _ = bundle
    payload = backup / "artifacts/payload.wav"
    if fault == "missing":
        payload.unlink()
    elif fault == "changed":
        payload.write_bytes(b"different bytes")
    elif fault == "extra":
        (backup / "artifacts/unlisted").write_bytes(b"extra")
    elif fault == "symlink":
        payload.unlink()
        payload.symlink_to(backup / "beta.pgdump")
    else:
        (backup / "beta.pgdump").unlink()
    with pytest.raises(BackupCheckError):
        verify_backup(backup, root)


@pytest.mark.parametrize("fault", ["traversal", "absolute", "duplicate", "bad_digest"])
def test_manifest_paths_and_identity_are_validated(bundle, fault):
    root, _, backup, manifest = bundle
    if fault == "traversal":
        manifest["files"][0]["path"] = "../beta.pgdump"
    elif fault == "absolute":
        manifest["files"][0]["path"] = "/private/synthetic"
    elif fault == "duplicate":
        manifest["files"].append(manifest["files"][0])
    else:
        manifest["db_dump"]["sha256"] = "not-a-sha"
    (backup / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BackupCheckError):
        verify_backup(backup, root)


def test_declared_appledouble_requires_header_and_companion(bundle):
    root, _, backup, manifest = bundle
    raw = bytes.fromhex("0005160700020000") + b"\0" * 18
    metadata = backup / "artifacts/._payload.wav"
    metadata.write_bytes(raw)
    manifest["platform_metadata"] = [
        {"path": metadata.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    ]
    (backup / "manifest.json").write_text(json.dumps(manifest))
    assert verify_backup(backup, root)["platform_metadata_files"] == 1
    metadata.write_bytes(b"forged" + raw[6:])
    with pytest.raises(BackupCheckError):
        verify_backup(backup, root)


def test_plans_reject_existing_target_and_source_overlap(bundle):
    root, source, backup, _ = bundle
    with pytest.raises(BackupCheckError):
        plan_backup(source, source / "nested-backup", root)
    with pytest.raises(BackupCheckError):
        plan_backup(source, backup, root)
    with pytest.raises(BackupCheckError):
        plan_restore(backup, source, root)
    with pytest.raises(BackupCheckError):
        plan_restore(backup, backup / "restore", root)
    with pytest.raises(BackupCheckError):
        plan_restore(backup, root.parent / "outside", root)


def test_allowed_root_and_path_components_cannot_be_symlinks(bundle):
    root, _, backup, _ = bundle
    alias = root / "alias"
    alias.symlink_to(backup, target_is_directory=True)
    with pytest.raises(BackupCheckError):
        verify_backup(alias, root)
    with pytest.raises(BackupCheckError):
        verify_backup(backup, alias)


def test_dry_run_never_creates_target_or_claims_restore_readiness(bundle, capsys):
    root, source, backup, _ = bundle
    target = root / "fresh-restore"
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    result = plan_restore(backup, target, root)
    assert result["ready_for_real_restore"] is False
    assert result["restore_performed"] is False
    assert not target.exists()
    assert before == sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    assert plan_backup(source, root / "next-backup", root)["backup_performed"] is False
    assert (
        main(
            [
                "restore",
                "--dry-run",
                "--allowed-root",
                str(root),
                "--backup",
                str(backup),
                "--target",
                str(target),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["restore_performed"] is False
    assert not target.exists()


def test_cli_requires_dry_run_and_outputs_only_safe_error(bundle, capsys):
    root, _, backup, _ = bundle
    with pytest.raises(SystemExit):
        main(
            [
                "restore",
                "--allowed-root",
                str(root),
                "--backup",
                str(backup),
                "--target",
                str(root / "target"),
            ]
        )
    capsys.readouterr()
    assert main(["verify", "--allowed-root", str(root), "--backup", str(root / "missing")]) == 2
    output = capsys.readouterr().out
    assert str(root) not in output
    assert json.loads(output)["error"].startswith("BACKUP_")


def test_manifest_symlink_and_oversize_are_rejected_before_parsing(bundle):
    root, _, backup, _ = bundle
    manifest = backup / "manifest.json"
    manifest.unlink()
    manifest.symlink_to(backup / "beta.pgdump")
    with pytest.raises(BackupCheckError, match="BACKUP_MANIFEST_INVALID"):
        verify_backup(backup, root)
    manifest.unlink()
    manifest.write_bytes(b" " * (1024**2 + 1))
    with pytest.raises(BackupCheckError, match="BACKUP_MANIFEST_BUDGET_EXCEEDED"):
        verify_backup(backup, root)


def test_cli_symlink_loop_returns_safe_error_without_path(bundle, capsys):
    root, _, _, _ = bundle
    loop = root / "loop"
    loop.symlink_to(loop)
    assert main(["verify", "--allowed-root", str(root), "--backup", str(loop)]) == 2
    assert str(root) not in capsys.readouterr().out


def test_manifest_fifo_is_rejected_before_open(bundle, monkeypatch):
    import scripts.personal_beta_backup as checker

    root, _, backup, _ = bundle
    manifest = backup / "manifest.json"
    manifest.unlink()
    os.mkfifo(manifest)

    def cannot_open(*_args):
        pytest.fail("special manifest must be rejected before opening")

    monkeypatch.setattr(checker.os, "open", cannot_open)
    with pytest.raises(BackupCheckError, match="BACKUP_MANIFEST_INVALID"):
        verify_backup(backup, root)


def test_all_reads_use_nonblocking_nofollow_open(bundle, monkeypatch):
    import scripts.personal_beta_backup as checker

    root, _, backup, _ = bundle
    original = checker.os.open
    opened = []

    def checked_open(path, flags):
        assert flags & os.O_NONBLOCK
        assert flags & os.O_NOFOLLOW
        opened.append(path)
        return original(path, flags)

    monkeypatch.setattr(checker.os, "open", checked_open)
    assert verify_backup(backup, root)["integrity"] == "verified"
    assert len(opened) == 3
