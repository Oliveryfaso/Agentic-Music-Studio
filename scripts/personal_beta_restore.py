"""Explicit v2 restore into a pre-created isolated PG; default is dry-run.

Never creates containers or deletes evidence. The supervisor stops only the
admitted temporary PG. No API startup or migration.
"""

import argparse
import hashlib
import json
import multiprocessing
import os
import plistlib
import re
import signal
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from scripts import personal_beta_backup_archive as archive
from scripts.personal_beta_backup_runtime import BackupRuntimeError, DockerBackupRuntime, _OwnedCLI
from scripts.restore_diagnostics import Diagnostics, RestoreFailure

REVISION = "20261020_0030"
require = archive.require


def inspect_target_volume(parent, cli):
    """Resolve a directory to its actual device; no mount or permission changes."""
    parent = archive.checks._root(Path(parent))
    before = parent.stat()

    def device():
        raw = cli.run(["/bin/df", "-P", str(parent)]).decode("utf-8")
        lines = raw.strip().splitlines()
        require(len(lines) == 2, "RESTORE_DEVICE_QUERY")
        columns = lines[1].split()
        require(
            bool(columns)
            and re.fullmatch(r"/dev/disk[0-9]+s[0-9]+(?:s[0-9]+)?", columns[0]) is not None,
            "RESTORE_DEVICE_QUERY",
        )
        return columns[0]

    node = device()
    info = plistlib.loads(cli.run(["/usr/sbin/diskutil", "info", "-plist", node]))
    require(
        isinstance(info, dict)
        and not info.get("Error")
        and info.get("FilesystemType") == "apfs"
        and info.get("Writable") is True,
        "RESTORE_REQUIRES_WRITABLE_APFS",
    )
    require(
        info.get("DeviceIdentifier") == node.removeprefix("/dev/")
        and info.get("DeviceNode") == node,
        "RESTORE_VOLUME_IDENTITY",
    )
    mount = archive.checks._root(Path(info["MountPoint"]))
    mounted = mount.stat()
    after = parent.stat()
    require(
        parent.resolve(strict=True) == parent
        and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
        and mounted.st_dev == after.st_dev
        and device() == node,
        "RESTORE_VOLUME_CHANGED",
    )
    return info


class RestoreRuntime(DockerBackupRuntime):
    def __init__(self, contract):
        self.contract = contract
        self.pg = contract["pg_id"]
        self.cli = _OwnedCLI()
        self.remote_exec_unknown = False

    def admit(self, parent):
        inspect_target_volume(parent, self.cli)
        require(
            self._docker(["info", "--format", "{{.ID}}"]).decode().strip()
            == self.contract["daemon_id"],
            "RESTORE_DAEMON_MISMATCH",
        )
        row = json.loads(self._docker(["inspect", self.pg]))[0]
        created = datetime.fromisoformat(row["Created"].replace("Z", "+00:00"))
        age = (datetime.now(UTC) - created).total_seconds()
        require(0 <= age < 120, "RESTORE_PG_NOT_NEW")
        self.container_deadline = time.monotonic() + 900 - age
        self.proof = (row["Id"], row["Image"], row["Created"])
        host = row["HostConfig"]
        labels = row["Config"].get("Labels") or {}
        require(
            row["Id"] == self.pg and row["Image"] == self.contract["pg_image"],
            "RESTORE_PG_IDENTITY",
        )
        require(
            labels.get("io.motif.restore.owner") == self.contract["owner"]
            and not any(k.startswith("com.docker.compose") for k in labels),
            "RESTORE_NOT_OWNED",
        )
        require(row["State"]["Running"] and row["RestartCount"] == 0, "RESTORE_PG_STATE")
        require(
            not row.get("Mounts") or all(m["Type"] == "tmpfs" for m in row["Mounts"]),
            "RESTORE_PERSISTENT_MOUNT",
        )
        require(
            host.get("Memory") == 384 * 1024**2
            and host.get("MemorySwap") == host["Memory"]
            and host.get("PidsLimit") == 64
            and host.get("NanoCpus") == 1000000000,
            "RESTORE_RESOURCE_LIMIT",
        )
        require(
            not host.get("PublishAllPorts")
            and not any(row["NetworkSettings"].get("Ports", {}).values()),
            "RESTORE_PUBLISHED_PORT",
        )
        require(
            not host.get("Privileged")
            and not host.get("PortBindings")
            and host.get("ReadonlyRootfs") is True,
            "RESTORE_HOST_ACCESS",
        )
        require(host.get("RestartPolicy", {}).get("Name") == "no", "RESTORE_RESTART_POLICY")
        tmp = host.get("Tmpfs") or {}
        require(
            set(tmp) == {"/var/lib/postgresql/data", "/var/run/postgresql", "/tmp"}, "RESTORE_TMPFS"
        )
        require(
            tmpfs_size(tmp["/var/lib/postgresql/data"]) == 268435456
            and tmpfs_size(tmp["/var/run/postgresql"]) == 8388608
            and tmpfs_size(tmp["/tmp"]) == 67108864,
            "RESTORE_TMPFS_BUDGET",
        )
        nets = row["NetworkSettings"]["Networks"]
        require(len(nets) == 1, "RESTORE_NETWORK")
        netid = next(iter(nets.values()))["NetworkID"]
        net = json.loads(self._docker(["network", "inspect", netid]))[0]
        require(
            net["Internal"]
            and (net.get("Labels") or {}).get("io.motif.restore.owner") == self.contract["owner"]
            and set(net["Containers"]) == {self.pg},
            "RESTORE_NETWORK",
        )
        # Empty, fresh DB only; same fixed DB name permits original snapshot reuse.
        empty = self._sql(
            "SELECT (NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' "
            "AND n.nspname <> 'information_schema') AND NOT EXISTS "
            "(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
            "AND pid<>pg_backend_pid()))::text"
        )
        require(empty == "true", "RESTORE_DATABASE_NOT_EMPTY")

    def restore(self, dump):
        diagnostics = getattr(self, "diagnostics", None)
        if diagnostics:
            diagnostics.stage("dump_copy")
        # Daemon archive-copy does not write the live tmpfs of a readonly
        # container. Stream into a non-root, exclusive in-container file.
        try:
            fd = os.open(dump, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            raise BackupRuntimeError("BACKUP_STDIN_INVALID") from None
        with os.fdopen(fd, "rb") as source:
            transfer = self._exec()
            transfer.insert(1, "-i")
            transfer += ["/bin/sh", "-c", "umask 077; set -C; cat > /tmp/restore.pgdump"]
            self._docker(transfer, stdin_file=source)
        if diagnostics:
            diagnostics.stage("dump_copy", "completed")
        args = self._exec()
        args = [x for x in args if not x.startswith("PGOPTIONS=")]
        args += [
            "pg_restore",
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-privileges",
            "--no-password",
            "--host=/var/run/postgresql",
            "-U",
            "motif_forge",
            "-d",
            "motif_forge",
            "/tmp/restore.pgdump",
        ]
        before = len(getattr(getattr(self, "cli", None), "children", ()))
        if diagnostics:
            diagnostics.pg_restore_started = True
            diagnostics.stage("pg_restore")
        try:
            self._docker(args, timeout=120)
        except BaseException:
            children = getattr(getattr(self, "cli", None), "children", ())
            if diagnostics and len(children) == before + 1:
                child = children[-1]
                code = child.returncode
                if (
                    getattr(child, "backup_waited", False)
                    and type(code) is int
                    and -128 <= code <= 255
                ):
                    diagnostics.pg_restore_cli_exit = code
            raise
        if diagnostics:
            diagnostics.pg_restore_cli_exit = 0
            diagnostics.stage("pg_restore", "completed")


def tmpfs_size(value):
    options = {}
    for entry in value.split(","):
        k, sep, v = entry.partition("=")
        require(
            k not in options
            and k in {"size", "mode", "uid", "gid", "nr_inodes", "rw", "nosuid", "nodev", "noexec"},
            "RESTORE_TMPFS_OPTION",
        )
        require(
            (sep and v.isdigit()) or (not sep and k in {"rw", "nosuid", "nodev", "noexec"}),
            "RESTORE_TMPFS_OPTION",
        )
        options[k] = v
    require("size" in options, "RESTORE_TMPFS_SIZE")
    return int(options["size"])


def bounded_hash(stream, remaining):
    require(os.fstat(stream.fileno()).st_size <= archive.MAX_ARCHIVE_BYTES, "RESTORE_ARCHIVE_SIZE")
    h = hashlib.sha256()
    total = 0
    while True:
        require(remaining() > 0, "RESTORE_DEADLINE")
        chunk = stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        require(total <= archive.MAX_ARCHIVE_BYTES, "RESTORE_ARCHIVE_SIZE")
        h.update(chunk)
    return h.hexdigest()


def validate(c):
    require(
        set(c)
        == {
            "archive",
            "archive_root",
            "archive_sha256",
            "target",
            "target_root",
            "owner",
            "daemon_id",
            "pg_id",
            "pg_image",
            "expected_db_revision",
        },
        "RESTORE_CONTRACT_FIELDS",
    )
    require(
        isinstance(c["archive_sha256"], str)
        and re.fullmatch("[0-9a-f]{64}", c["archive_sha256"]) is not None,
        "RESTORE_ARCHIVE_PIN_INVALID",
    )
    require(re.fullmatch("[0-9a-f]{32}", c["owner"]) is not None, "RESTORE_OWNER")
    require(
        re.fullmatch("[0-9a-f]{64}", c["pg_id"]) is not None
        and re.fullmatch("sha256:[0-9a-f]{64}", c["pg_image"]) is not None,
        "RESTORE_IDENTITY",
    )
    require(c["expected_db_revision"] == REVISION, "RESTORE_SCHEMA")
    target = Path(c["target"])
    root = archive.checks._root(Path(c["target_root"]))
    archive.checks._inside(target, root, exists=False)
    require(
        not target.exists() and not target.is_symlink() and target.parent.is_dir(),
        "RESTORE_TARGET_NOT_FRESH",
    )
    return target


def _source_identity_overlap(target, source):
    """A present source must not reappear under a case/normalization alias."""
    try:
        origin = source.stat()
    except FileNotFoundError:
        # Backups remain usable after removal of the original source.
        return False
    except OSError:
        raise archive.checks.BackupCheckError("RESTORE_SOURCE_IDENTITY_UNKNOWN") from None
    identity = (origin.st_dev, origin.st_ino)
    for parent in (target.parent, *target.parent.parents):
        try:
            current = parent.stat()
        except OSError:
            raise archive.checks.BackupCheckError("RESTORE_SOURCE_IDENTITY_UNKNOWN") from None
        if (current.st_dev, current.st_ino) == identity:
            return True
    return False


def run(c, execute=False, factory=RestoreRuntime, diagnostics=None):
    d = diagnostics if diagnostics is not None else Diagnostics()
    runtime = None
    try:
        d.stage("contract")
        target = validate(c)
        if not execute:
            return {"status": "DRY_RUN", "restore_performed": False, "runtime_verified": False}
        runtime = factory(c)
        runtime.diagnostics = d
        d.stage("contract", "completed")
        d.stage("archive_open")
        with archive._locked_archive(Path(c["archive"]), Path(c["archive_root"])) as stream:
            d.stage("archive_open", "completed")
            d.stage("archive_verify")
            digest = bounded_hash(stream, runtime.cli._remaining)
            require(digest == c["archive_sha256"], "RESTORE_ARCHIVE_PIN")
            stream.seek(0)
            manifest, summary = archive.verify_stream(stream)
            require(manifest["schema_revision"] == REVISION, "RESTORE_SCHEMA")
            require(
                not archive.checks._overlap(target, Path(manifest["source_root"]))
                and not archive.checks._overlap(target, Path(c["archive"]))
                and not _source_identity_overlap(target, Path(manifest["source_root"])),
                "RESTORE_SOURCE_OVERLAP",
            )
            space = os.statvfs(target.parent)
            require(
                space.f_bavail * space.f_frsize
                >= summary["artifact_bytes"] + summary["dump_bytes"] + 512 * 1024**2,
                "RESTORE_SPACE",
            )
            d.stage("archive_verify", "completed")
            d.stage("child_admission")
            runtime.admit(target.parent)
            d.stage("child_admission", "completed")
            d.stage("media_extract")
            target.mkdir(mode=0o700)
            with zipfile.ZipFile(stream) as z:
                for name in ["media", "dump"]:
                    (target / name).mkdir(mode=0o700)
                for name in sorted(manifest["directories"], key=lambda n: (n.count("/"), n)):
                    (target / "media" / name).mkdir(mode=0o700, parents=True, exist_ok=True)
                rows = [("media/" + r["path"], r) for r in manifest["files"]] + [
                    (manifest["db_dump"]["path"], manifest["db_dump"])
                ]
                for name, row in rows:
                    runtime.cli._remaining()
                    path = target / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    h = hashlib.sha256()
                    size = 0
                    with z.open(name) as inp, path.open("xb") as out:
                        while chunk := inp.read(65536):
                            size += len(chunk)
                            require(size <= row["bytes"], "RESTORE_SIZE")
                            out.write(chunk)
                            h.update(chunk)
                        out.flush()
                        os.fsync(out.fileno())
                    require(size == row["bytes"] and h.hexdigest() == row["sha256"], "RESTORE_HASH")
            d.stage("media_extract", "completed")
            d.stage("target_readmit")
            runtime.admit(target.parent)
            d.stage("target_readmit", "completed")
            d.stage("restore_dispatch")
            runtime.restore(target / "dump/beta.pgdump")
            d.stage("restore_dispatch", "completed")
            d.stage("db_snapshot")
            actual = runtime.snapshot()
            d.stage("db_snapshot", "completed")
            d.stage("db_compare")
            require(
                actual["tables"] == manifest["db_tables"]
                and actual["sequences"] == manifest["db_sequences"],
                "RESTORE_DATABASE_MISMATCH",
            )
            d.db_verified = True
            d.stage("db_compare", "completed")
            d.stage("archive_close")
        d.stage("archive_close", "completed")
    except BaseException as error:
        d.fail(d.current_stage, error)
    finally:
        if runtime is not None:
            d.cleanup("client_close", runtime.close)
    result = d.result(success=True)
    if result["status"] != "RESTORED_PG_AND_MEDIA":
        raise RestoreFailure(result) from None
    return result


def _cancel(signum, frame):
    raise KeyboardInterrupt


def _restore_child(c, pipe):
    signal.signal(signal.SIGTERM, _cancel)
    d = Diagnostics(observer=pipe.send)
    try:
        d.stage("device_separation")
        require(
            os.stat(c["archive"]).st_dev != os.stat(Path(c["target"]).parent).st_dev,
            "RESTORE_DEVICE_NOT_ISOLATED",
        )
        d.stage("device_separation", "completed")
        result = run(c, True, diagnostics=d)
    except BaseException as error:
        d.fail(d.current_stage, error)
        result = d.result()
    try:
        pipe.send({"kind": "result", "result": result})
    except BaseException:
        pass  # Parent has no terminal receipt and must retain UNKNOWN.
    finally:
        try:
            pipe.close()
        except BaseException:
            raise SystemExit(2) from None


def stop_proven_target(runtime):
    # A separate CLI owner is unaffected by the child's poisoned exec connection.
    cli = _OwnedCLI()
    d = Diagnostics()

    def docker(args, timeout=15):
        return cli.run(["docker", "--context", "colima", *args], timeout=timeout)

    try:
        require(
            docker(["info", "--format", "{{.ID}}"]).decode().strip()
            == runtime.contract["daemon_id"],
            "RESTORE_STOP_DAEMON",
        )
        row = json.loads(docker(["inspect", runtime.pg]))[0]
        require((row["Id"], row["Image"], row["Created"]) == runtime.proof, "RESTORE_STOP_IDENTITY")
        require(
            (row["Config"].get("Labels") or {}).get("io.motif.restore.owner")
            == runtime.contract["owner"]
            and not any(
                k.startswith("com.docker.compose") for k in (row["Config"].get("Labels") or {})
            ),
            "RESTORE_STOP_OWNER",
        )
        require(all(m["Type"] == "tmpfs" for m in row.get("Mounts", [])), "RESTORE_STOP_MOUNT")
        if row["State"]["Running"]:
            docker(["stop", "--time", "8", runtime.pg])
        docker(["wait", runtime.pg])
        after = json.loads(docker(["inspect", runtime.pg]))[0]
        require(
            (after["Id"], after["Image"], after["Created"]) == runtime.proof
            and not after["State"]["Running"]
            and after["State"]["Pid"] == 0,
            "RESTORE_TARGET_EXIT_UNKNOWN",
        )
    except BaseException as error:
        d.fail("target_stop", error)
    finally:
        d.cleanup("client_close", cli.close)
    if d.first_error is not None or d.cleanup_errors:
        raise RestoreFailure(d.result()) from None


def supervised(c):
    d = Diagnostics()
    parent = None
    child = None
    receiver = None
    sender = None
    admitted = False
    received_terminal = False
    received_events = False
    waiting = False
    old_term = signal.signal(signal.SIGTERM, _cancel)
    try:
        d.stage("contract")
        target = validate(c)
        parent = RestoreRuntime(c)
        d.stage("contract", "completed")
        d.stage("parent_admission")
        parent.admit(target.parent)
        admitted = True
        d.stage("parent_admission", "completed")
        d.stage("worker_spawn")
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        child = context.Process(target=_restore_child, args=(c, sender))
        child.start()
        sender.close()
        sender = None
        d.stage("worker_spawn", "completed")
        deadline = min(time.monotonic() + 780, parent.container_deadline - 90)
        d.stage("worker_wait")
        waiting = True
        while time.monotonic() < deadline:
            if receiver.poll(0.2):
                frame = receiver.recv()
                if isinstance(frame, dict) and frame.get("kind") == "stage":
                    d.accept_event(frame)
                    received_events = True
                    continue
                require(
                    isinstance(frame, dict)
                    and set(frame) == {"kind", "result"}
                    and frame["kind"] == "result",
                    "RESTORE_WORKER_UNKNOWN",
                )
                d.adopt(frame["result"], include_events=not received_events)
                received_terminal = True
                break
            if not child.is_alive():
                break
        child.join(timeout=1)
        d.host_child_waited = child.exitcode is not None and not child.is_alive()
        if not received_terminal or not d.host_child_waited or child.exitcode != 0:
            d.uncertain = True
            raise RuntimeError("RESTORE_WORKER_UNKNOWN")
        d.stage("worker_wait", "completed")
        if not d.db_verified and d.first_error is None:
            raise RuntimeError("RESTORE_WORKER_FAILED")
    except BaseException as error:
        if not received_terminal:
            d.uncertain = child is not None
        if isinstance(error, (EOFError, BrokenPipeError)):
            error = RuntimeError("RESTORE_WORKER_UNKNOWN")
        d.fail("worker_wait" if waiting else d.current_stage, error)
    finally:
        if admitted:
            d.target_exit_proven = d.cleanup("target_stop", lambda: stop_proven_target(parent))
        if child is not None and child.pid is not None:

            def child_exit():
                if child.is_alive():
                    child.terminate()
                child.join(timeout=5)
                if child.is_alive():
                    child.kill()
                    child.join(timeout=2)
                    d.host_child_waited = child.exitcode is not None and not child.is_alive()
                    raise RuntimeError("RESTORE_HOST_DESCENDANT_EXIT_UNKNOWN")
                require(not child.is_alive(), "RESTORE_HOST_EXIT_UNKNOWN")
                d.host_child_waited = child.exitcode is not None

            d.cleanup("worker_exit", child_exit)
        if receiver is not None:
            d.cleanup("event_transport", receiver.close)
        if sender is not None:
            d.cleanup("event_transport", sender.close)
        if parent is not None:
            d.cleanup("parent_close", parent.close)
        d.cleanup("signal_restore", lambda: signal.signal(signal.SIGTERM, old_term))
    result = d.result(success=received_terminal and d.host_child_waited and d.target_exit_proven)
    if result["status"] != "RESTORED_PG_AND_MEDIA":
        raise RestoreFailure(result) from None
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    began_supervised = False
    try:
        c = archive.checks._manifest(a.contract)
        began_supervised = a.execute
        result = supervised(c) if a.execute else run(c, False)
    except RestoreFailure as error:
        print(json.dumps(error.as_result()))
        return 2
    except (Exception, KeyboardInterrupt) as error:
        d = Diagnostics()
        d.uncertain = began_supervised
        d.fail("entry", error)
        print(json.dumps(d.result()))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
