import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_personal_beta_backup_archive_create import DatabaseStub

from scripts import personal_beta_backup_archive_create as creator
from scripts import personal_beta_restore as r


@pytest.fixture
def case(contract):
    creator.create_archive_backup(contract, execute=True, factory=lambda _: DatabaseStub())
    path = Path(contract["destination"])
    return dict(
        archive=str(path),
        archive_root=contract["allowed_root"],
        archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        target=str(path.parent / "restored"),
        target_root=contract["allowed_root"],
        owner="a" * 32,
        daemon_id="synthetic",
        pg_id="1" * 64,
        pg_image="sha256:" + "2" * 64,
        expected_db_revision=r.REVISION,
    )


class Fake:
    def __init__(self):
        self.calls = []
        self.cli = SimpleNamespace(_remaining=lambda: 100)
        self.closed = False

    def admit(self, p):
        self.calls.append("admit")

    def restore(self, p):
        assert p.read_bytes().startswith(b"PGDMP")
        self.calls.append("restore")

    def snapshot(self):
        self.calls.append("snapshot")
        return {"tables": [], "sequences": []}

    def close(self):
        self.closed = True


def test_default_no_archive_or_runtime(case):
    case["archive"] = "missing"
    assert r.run(case, factory=lambda _: pytest.fail("runtime"))["status"] == "DRY_RUN"
    assert not Path(case["target"]).exists()


def test_real_reader_synthetic_restore(case):
    f = Fake()
    result = r.run(case, True, lambda _: f)
    assert result["status"] == "RESTORED_PG_AND_MEDIA" and not result["api_verified"]
    assert (Path(case["target"]) / "media/audio.wav").read_bytes() == b"synthetic audio"
    assert f.calls == ["admit", "admit", "restore", "snapshot"] and f.closed


@pytest.mark.parametrize("kind", ["existing", "symlink", "schema", "pin", "overlap"])
def test_rejection(case, kind):
    target = Path(case["target"])
    if kind == "existing":
        target.mkdir()
    if kind == "symlink":
        target.symlink_to(target.parent / "absent")
    if kind == "schema":
        case["expected_db_revision"] = "0031"
    if kind == "pin":
        case["archive_sha256"] = "0" * 64
    if kind == "overlap":
        case["target"] = str(target.parent / "source" / "nested")
    f = Fake()
    with pytest.raises(r.RestoreFailure):
        r.run(case, True, lambda _: f)
    assert not f.calls


def test_failure_retains_files(case):
    f = Fake()

    def fail(p):
        raise RuntimeError("fake failure")

    f.restore = fail
    with pytest.raises(RuntimeError):
        r.run(case, True, lambda _: f)
    assert (Path(case["target"]) / "dump/beta.pgdump").exists() and f.closed


def test_mismatch_never_passes(case):
    f = Fake()
    f.snapshot = lambda: {"tables": ["changed"], "sequences": []}
    with pytest.raises(r.RestoreFailure):
        r.run(case, True, lambda _: f)
    assert f.closed


def test_pg_restore_command_is_bounded(tmp_path):
    runtime = object.__new__(r.RestoreRuntime)
    runtime.pg = "1" * 64
    calls = []
    runtime._docker = lambda args, **kw: calls.append((args, kw))
    dump = tmp_path / "synthetic.pgdump"
    dump.write_bytes(b"PGDMPsynthetic")
    runtime.restore(dump)
    argv = calls[-1][0]
    assert "pg_restore" in argv and "--single-transaction" in argv and "--exit-on-error" in argv
    assert "--clean" not in argv and not any(a.startswith("PGOPTIONS=") for a in argv)
    assert calls[-1][1]["timeout"] == 120


@pytest.mark.parametrize(
    "bad",
    [
        "none",
        "mount",
        "port",
        "owner",
        "memory",
        "network",
        "database",
        "fs",
        "publish_all",
        "actual_port",
        "large_tmpfs",
        "duplicate_size",
    ],
)
def test_actual_admission_with_fake_commands(bad, monkeypatch):
    import json
    import plistlib

    rt = object.__new__(r.RestoreRuntime)
    rt.pg = "1" * 64
    rt.contract = {"daemon_id": "daemon", "owner": "a" * 32, "pg_image": "sha256:" + "2" * 64}
    row = {
        "Created": datetime.now(UTC).isoformat(),
        "Id": rt.pg,
        "Image": rt.contract["pg_image"],
        "Config": {"Labels": {"io.motif.restore.owner": "a" * 32}},
        "State": {"Running": True},
        "RestartCount": 0,
        "Mounts": [],
        "HostConfig": {
            "Memory": 384 * 1024**2,
            "MemorySwap": 384 * 1024**2,
            "PidsLimit": 64,
            "NanoCpus": 1000000000,
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "no"},
            "Tmpfs": {
                "/var/lib/postgresql/data": "size=268435456",
                "/var/run/postgresql": "size=8388608",
                "/tmp": "size=67108864",
            },
        },
        "NetworkSettings": {"Networks": {"test": {"NetworkID": "net"}}},
    }
    net = {
        "Internal": True,
        "Labels": {"io.motif.restore.owner": "a" * 32},
        "Containers": {rt.pg: {}},
    }
    if bad == "mount":
        row["Mounts"] = [{"Type": "bind"}]
    if bad == "port":
        row["HostConfig"]["PortBindings"] = {"5432": []}
    if bad == "owner":
        row["Config"]["Labels"] = {}
    if bad == "memory":
        row["HostConfig"]["Memory"] = 0
    if bad == "publish_all":
        row["HostConfig"]["PublishAllPorts"] = True
    if bad == "actual_port":
        row["NetworkSettings"]["Ports"] = {"5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32768"}]}
    if bad == "large_tmpfs":
        row["HostConfig"]["Tmpfs"]["/tmp"] = "size=671088640"
    if bad == "duplicate_size":
        row["HostConfig"]["Tmpfs"]["/tmp"] = "size=67108864,size=671088640"
    if bad == "network":
        net["Internal"] = False
    rt.cli = SimpleNamespace(
        run=lambda _: plistlib.dumps({"FilesystemType": "exfat" if bad == "fs" else "apfs"})
    )

    def volume(parent, cli):
        if bad == "fs":
            raise ValueError("RESTORE_REQUIRES_APFS")

    monkeypatch.setattr(r, "inspect_target_volume", volume)
    rt._sql = lambda _: "false" if bad == "database" else "true"

    def docker(args):
        if args[0] == "info":
            return b"daemon"
        return json.dumps([net if args[0] == "network" else row]).encode()

    rt._docker = docker
    if bad == "none":
        rt.admit(Path("/synthetic"))
    else:
        with pytest.raises(ValueError):
            rt.admit(Path("/synthetic"))


def test_archive_size_rejected_before_payload(tmp_path):
    from unittest.mock import Mock

    assert callable(r.bounded_hash)
    path = tmp_path / "large"
    with path.open("wb") as f:
        f.truncate(r.archive.MAX_ARCHIVE_BYTES + 1)
    with path.open("rb") as stream:
        guard = Mock(wraps=stream)
        with pytest.raises(r.archive.checks.BackupCheckError):
            r.bounded_hash(guard, lambda: 100)
        guard.read.assert_not_called()


@pytest.mark.parametrize("drift", [False, True])
def test_supervisor_stop_proof_no_production(monkeypatch, drift):
    import json

    rt = type("R", (), {})()
    rt.pg = "1" * 64
    rt.contract = {"daemon_id": "d", "owner": "o"}
    rt.proof = (rt.pg, "image", "created")
    calls = []
    inspections = 0

    class CLI:
        def run(self, args, **kwargs):
            nonlocal inspections
            args = args[3:]
            calls.append(args)
            if args[0] == "info":
                return b"d"
            if args[0] == "inspect":
                inspections += 1
                return json.dumps(
                    [
                        {
                            "Id": rt.pg,
                            "Image": "other" if drift else "image",
                            "Created": "created",
                            "Config": {"Labels": {"io.motif.restore.owner": "o"}},
                            "Mounts": [],
                            "State": {
                                "Running": inspections == 1,
                                "Pid": 1 if inspections == 1 else 0,
                            },
                        }
                    ]
                ).encode()
            return b"0"

        def close(self):
            pass

    monkeypatch.setattr(r, "_OwnedCLI", CLI)
    if drift:
        with pytest.raises(r.RestoreFailure):
            r.stop_proven_target(rt)
        assert not any(c[0] in ("stop", "wait") for c in calls)
    else:
        r.stop_proven_target(rt)
        assert ["stop", "--time", "8", rt.pg] in calls and ["wait", rt.pg] in calls


def test_supervised_blocked_child_cannot_block_parent(monkeypatch):
    """Actual supervisor, fake stalled child: archive stat must never run in parent."""
    clock = [0.0]
    events = []

    class Parent:
        def __init__(self, c):
            self.container_deadline = 900

        def admit(self, path):
            events.append(("admit", clock[0]))

        def close(self):
            events.append(("close", clock[0]))

    class Pipe:
        def poll(self, timeout):
            clock[0] += 100
            return False

        def close(self):
            pass

    class Child:
        pid = 123
        exitcode = None
        alive = True

        def start(self):
            events.append(("start", clock[0]))

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            pass

        def terminate(self):
            self.alive = False
            self.exitcode = -15

    child = Child()
    context = SimpleNamespace(Pipe=lambda **kw: (Pipe(), Pipe()), Process=lambda **kw: child)
    monkeypatch.setattr(r, "validate", lambda c: Path("/synthetic/new"))
    monkeypatch.setattr(r, "RestoreRuntime", Parent)
    monkeypatch.setattr(r.multiprocessing, "get_context", lambda _: context)
    monkeypatch.setattr(r.time, "monotonic", lambda: clock[0])

    def stat(_):
        clock[0] += 950
        raise RuntimeError("parent performed external I/O")

    monkeypatch.setattr(r, "os", SimpleNamespace(stat=stat))
    monkeypatch.setattr(r, "stop_proven_target", lambda p: events.append(("stop", clock[0])))
    with pytest.raises(r.RestoreFailure):
        r.supervised({"archive": "/external/backup"})
    assert ("start", 0.0) in events
    assert next(t for e, t in events if e == "stop") < 900
    assert not child.alive


def test_main_cancel_has_fixed_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["restore", "--contract", "synthetic", "--execute"])
    monkeypatch.setattr(r.archive.checks, "_manifest", lambda _: {})

    def cancel(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(r, "supervised", cancel)
    try:
        status = r.main()
    except KeyboardInterrupt:
        pytest.fail("cancellation escaped fixed JSON boundary")
    assert status == 2
    capture = capsys.readouterr()
    assert capture.err == ""
    import json

    result = json.loads(capture.out)
    assert result["status"] == "FAILED_OR_UNKNOWN" and result["reason"] == "RESTORE_STOPPED"
    assert result["preserve_evidence"] is True
    assert result["first_error"] == {
        "stage": "entry",
        "error_code": "RESTORE_CANCELLED",
        "error_type": "KeyboardInterrupt",
    }
    assert (
        result["restore_state"] == "unverified"
        and result["pg_restore_started"] is None
        and not result["db_verified"]
    )
