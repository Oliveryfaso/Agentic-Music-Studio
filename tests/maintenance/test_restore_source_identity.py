"""Protect a present source directory by filesystem identity, not just spelling."""

import errno
import json
from pathlib import Path

import pytest
from test_personal_beta_restore import Fake

from scripts import personal_beta_restore as r


def test_case_alias_cannot_restore_inside_present_source(case):
    source = Path(case["archive_root"]) / "source"
    alias = source.with_name("SOURCE")
    if not alias.is_dir() or not alias.samefile(source):
        pytest.skip("fixture filesystem does not alias upper/lowercase names")
    case["target"] = str(alias / "must-not-be-created")
    runtime = Fake()
    with pytest.raises(r.RestoreFailure) as caught:
        r.run(case, True, lambda _: runtime)
    assert caught.value.as_result()["first_error"]["error_code"] == "RESTORE_SOURCE_OVERLAP"
    assert runtime.calls == []
    assert not Path(case["target"]).exists()


def test_unknown_existing_source_identity_fails_closed_without_leaking_path(case, monkeypatch):
    source = Path(case["archive_root"]) / "source"
    original = Path.stat

    def denied(path, *args, **kwargs):
        if path == source:
            raise PermissionError(errno.EACCES, "SYNTHETIC_PRIVATE_SOURCE")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    runtime = Fake()
    with pytest.raises(r.RestoreFailure) as caught:
        r.run(case, True, lambda _: runtime)
    result = caught.value.as_result()
    assert result["first_error"]["error_code"] == "RESTORE_SOURCE_IDENTITY_UNKNOWN"
    assert "SYNTHETIC_PRIVATE_SOURCE" not in json.dumps(result)
    assert runtime.calls == []
    assert not Path(case["target"]).exists()


def test_backup_remains_restorable_when_original_source_no_longer_exists(case):
    source = Path(case["archive_root"]) / "source"
    source.rename(source.with_name("moved-synthetic-source"))
    runtime = Fake()
    result = r.run(case, True, lambda _: runtime)
    assert result["status"] == "RESTORED_PG_AND_MEDIA"
    assert runtime.calls == ["admit", "admit", "restore", "snapshot"]
