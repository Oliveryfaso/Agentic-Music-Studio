"""Real command output shapes, no diskutil or Docker execution."""

import plistlib
from types import SimpleNamespace

import pytest

from scripts import personal_beta_restore as r


@pytest.fixture
def volume(tmp_path):
    target = tmp_path / "with spaces" / "nested"
    target.mkdir(parents=True)
    info = {
        "FilesystemType": "apfs",
        "DeviceIdentifier": "disk3s5",
        "DeviceNode": "/dev/disk3s5",
        "MountPoint": str(tmp_path),
        "Writable": True,
    }
    calls = []

    def run(args):
        calls.append(args)
        if args[0] == "/bin/df":
            return (
                b"Filesystem 512-blocks Used Available Capacity Mounted on\n"
                b"/dev/disk3s5 100 20 80 20% /System/Volumes/Data\n"
            )
        assert args == ["/usr/sbin/diskutil", "info", "-plist", "/dev/disk3s5"]
        return plistlib.dumps(info)

    return target, info, calls, run


def test_nested_space_path_uses_device(volume):
    target, _, calls, run = volume
    assert callable(r.inspect_target_volume)
    result = r.inspect_target_volume(target, SimpleNamespace(run=run))
    assert result["FilesystemType"] == "apfs"
    assert calls[0] == ["/bin/df", "-P", str(target)]


@pytest.mark.parametrize(
    "change",
    [
        {"Error": True},
        {"FilesystemType": "exfat"},
        {"Writable": False},
        {"DeviceIdentifier": "disk9s1"},
        {"MountPoint": "/missing/synthetic"},
    ],
)
def test_bad_volume_rejected(volume, change):
    target, info, _, run = volume
    info.update(change)
    with pytest.raises((r.archive.checks.BackupCheckError, OSError)):
        r.inspect_target_volume(target, SimpleNamespace(run=run))


def test_link_rejected(volume):
    target, _, _, run = volume
    link = target.parent / "link"
    link.symlink_to(target)
    with pytest.raises((r.archive.checks.BackupCheckError, OSError)):
        r.inspect_target_volume(link, SimpleNamespace(run=run))


def test_device_changes_between_queries(volume):
    target, _, _, run = volume
    count = 0

    def changing(args):
        nonlocal count
        data = run(args)
        if args[0] == "/bin/df":
            count += 1
            if count == 2:
                return data.replace(b"disk3s5", b"disk9s1")
        return data

    with pytest.raises((r.archive.checks.BackupCheckError, OSError)):
        r.inspect_target_volume(target, SimpleNamespace(run=changing))


def test_parent_replaced_during_probe(volume):
    target, _, _, run = volume

    def replacing(args):
        data = run(args)
        if args[0] == "/usr/sbin/diskutil":
            target.rename(target.with_name("preserved"))
            target.mkdir()
        return data

    with pytest.raises((r.archive.checks.BackupCheckError, OSError)):
        r.inspect_target_volume(target, SimpleNamespace(run=replacing))
