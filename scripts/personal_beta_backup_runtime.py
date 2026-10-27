"""Read-only Docker adapter for an explicitly maintained personal Beta backup.

No service/resource lifecycle operations or credential lookup. The caller owns
the existing launcher lock and file/path contract. MD5 table summaries detect
cooperative maintenance drift; they are not a malicious-writer security proof.
CLI processes must not daemonize or create another session.
"""

from __future__ import annotations

import json
import os
import re
import select
import signal
import stat
import subprocess
import time
from contextlib import suppress
from typing import BinaryIO

SERVICES = frozenset(
    {
        "api",
        "dispatcher",
        "resume-dispatcher",
        "media-worker",
        "render-worker",
        "migrate",
        "storage-init",
        "postgres",
        "redis",
    }
)
WRITERS = SERVICES - {"postgres", "redis"}
ARTIFACT_WRITERS = frozenset(
    {"api", "storage-init", "resume-dispatcher", "media-worker", "render-worker"}
)
MAX_DB_BYTES = 64 * 1024**2
METADATA_BYTES = 64 * 1024
READ_ONLY = "PGOPTIONS=-c default_transaction_read_only=on"
IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*\Z")
ID = re.compile(r"[a-f0-9]{64}\Z")
ROW_DIGEST = re.compile(r"[a-f0-9]{32}\Z")


class BackupRuntimeError(RuntimeError):
    """Only fixed public codes; never include argv, raw stderr or private paths."""


def _require(condition: object, code: str) -> None:
    if not condition:
        raise BackupRuntimeError(code)


def _stderr_error_code(prefix: bytes) -> str:
    """Best-effort fixed categories; never return stderr text or its paths."""
    lower = prefix.lower()
    if b"service file" in lower or b"definition of service" in lower:
        return "BACKUP_CLI_SERVICE_FILE_ERROR"
    if b"socket" in lower and b"no such file" in lower:
        return "BACKUP_CLI_LOCAL_SOCKET_UNAVAILABLE"
    return "BACKUP_CLI_FAILED"


class _OwnedCLI:
    """One synchronous client, streamed output and an exact owned-group wait gate.

    Small adaptation of the reviewed synthetic backup helper: no tunnel/thread,
    80 work calls, 780s work / 900s total boundary. Only dump stdout may stream up
    to 64MiB; metadata and stderr remain bounded to 64KiB. No output is logged.
    """

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.children: list[subprocess.Popen[bytes]] = []
        self.poisoned = False
        self.closed = False
        self.calls = 0
        self.environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
            if key in os.environ
        }

    def _remaining(self, cleanup: bool = False) -> float:
        result = self.started + (900 if cleanup else 780) - time.monotonic()
        _require(result > 0, "BACKUP_RUNTIME_DEADLINE")
        return result

    def _finish(self, child: subprocess.Popen[bytes]) -> None:
        try:
            if child.poll() is None:
                for signum, grace in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 1.0)):
                    if child.poll() is not None:
                        break
                    _require(os.getpgid(child.pid) == child.pid, "BACKUP_CLI_EXIT_UNKNOWN")
                    os.killpg(child.pid, signum)
                    with suppress(subprocess.TimeoutExpired):
                        child.wait(timeout=min(grace, self._remaining(True)))
            _require(child.poll() is not None, "BACKUP_CLI_EXIT_UNKNOWN")
            code = child.wait(timeout=0)
            _require(type(code) is int, "BACKUP_CLI_EXIT_UNKNOWN")
            # Once the leader is reaped, never signal a possibly reused group.
            try:
                os.killpg(child.pid, 0)
            except ProcessLookupError:
                pass
            except OSError:
                raise BackupRuntimeError("BACKUP_CLI_EXIT_UNKNOWN") from None
            else:
                raise BackupRuntimeError("BACKUP_CLI_EXIT_UNKNOWN")
            child.backup_waited = True  # type: ignore[attr-defined]
        except BaseException:
            self.poisoned = True
            raise BackupRuntimeError("BACKUP_CLI_EXIT_UNKNOWN") from None
        finally:
            for pipe in (child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()

    def run(
        self,
        argv: list[str],
        *,
        sink: BinaryIO | None = None,
        stdin_file: BinaryIO | None = None,
        limit: int = METADATA_BYTES,
        timeout: float = 60,
    ) -> bytes:
        _require(not self.poisoned, "BACKUP_CLI_EXIT_UNKNOWN")
        _require(not self.closed and self.calls < 80, "BACKUP_CLI_CLOSED_OR_LIMIT")
        _require(type(limit) is int and 0 < limit <= MAX_DB_BYTES, "BACKUP_OUTPUT_LIMIT_INVALID")
        _require(sink is not None or limit <= METADATA_BYTES, "BACKUP_OUTPUT_LIMIT_INVALID")
        _require(
            all(getattr(c, "backup_waited", False) for c in self.children),
            "BACKUP_CLI_EXIT_UNKNOWN",
        )
        # Caller owns this already-verified, closed-writer dump. Borrow its
        # regular descriptor; never copy it into argv, memory, or another file.
        if stdin_file is not None:
            try:
                info = os.fstat(stdin_file.fileno())
                valid = (
                    stat.S_ISREG(info.st_mode)
                    and info.st_size <= MAX_DB_BYTES
                    and stdin_file.readable()
                    and stdin_file.tell() == 0
                )
            except (AttributeError, OSError, TypeError, ValueError):
                valid = False
            _require(valid, "BACKUP_STDIN_INVALID")
        duration = min(timeout, self._remaining())
        _require(duration > 0, "BACKUP_CLI_TIMEOUT")
        self.calls += 1
        child = None
        try:
            try:
                child = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL if stdin_file is None else stdin_file,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    bufsize=0,
                    env=self.environment,
                )
                child.backup_waited = False  # type: ignore[attr-defined]
                self.children.append(child)
            except BaseException:
                self.poisoned = True
                raise BackupRuntimeError("BACKUP_CLI_SPAWN_UNKNOWN") from None
            assert child.stdout is not None and child.stderr is not None
            output = bytearray()
            header = bytearray()
            diagnostic = bytearray()
            stdout_size = stderr_size = 0
            pipes = {child.stdout, child.stderr}
            for pipe in pipes:
                os.set_blocking(pipe.fileno(), False)
            deadline = time.monotonic() + duration
            while pipes or child.poll() is None:
                remaining = min(deadline - time.monotonic(), self._remaining())
                _require(remaining > 0, "BACKUP_CLI_TIMEOUT")
                ready, _, _ = select.select(list(pipes), [], [], min(0.05, remaining))
                for pipe in ready:
                    data = os.read(pipe.fileno(), 8192)
                    if not data:
                        pipes.remove(pipe)
                        continue
                    if pipe is child.stderr:
                        stderr_size += len(data)
                        _require(stderr_size <= METADATA_BYTES, "BACKUP_OUTPUT_LIMIT")
                        diagnostic.extend(data[: max(0, 2048 - len(diagnostic))])
                    else:
                        _require(stdout_size + len(data) <= limit, "BACKUP_OUTPUT_LIMIT")
                        stdout_size += len(data)
                        if sink is None:
                            output.extend(data)
                        else:
                            _require(sink.write(data) == len(data), "BACKUP_OUTPUT_WRITE_FAILED")
                            header.extend(data[: max(0, 5 - len(header))])
            _require(child.returncode == 0, _stderr_error_code(bytes(diagnostic)))
            return bytes(output if sink is None else header)
        except BackupRuntimeError:
            raise
        except BaseException:
            raise BackupRuntimeError("BACKUP_CLI_IO_FAILED") from None
        finally:
            if child is not None:
                self._finish(child)

    def close(self) -> None:
        self.closed = True
        _require(not self.poisoned, "BACKUP_CLI_EXIT_UNKNOWN")
        _require(
            all(getattr(c, "backup_waited", False) for c in self.children),
            "BACKUP_CLI_EXIT_UNKNOWN",
        )


INSPECT = (
    '{"Id":{{json .Id}},"Image":{{json .Image}},"State":{{json .State}},'
    '"Project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"Owner":{{json (index .Config.Labels "io.motif-forge.runtime-owner")}},'
    '"Service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"Mounts":{{json .Mounts}}}'
)

CATALOG = """SELECT json_build_object(
 'database', current_database(), 'db_bytes', pg_database_size(current_database()),
 'sessions', (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()
              AND pid<>pg_backend_pid() AND backend_type='client backend'),
 'schema_revision', (SELECT json_agg(version_num ORDER BY version_num) FROM public.alembic_version),
 'tables', (SELECT COALESCE(json_agg(x ORDER BY x.schema,x.name),'[]'::json) FROM
   (SELECT schemaname AS schema,tablename AS name FROM pg_tables
    WHERE schemaname NOT IN ('pg_catalog','information_schema')) x),
 'sequences', (SELECT COALESCE(json_agg(x ORDER BY x.schema,x.name),'[]'::json) FROM
   (SELECT sequence_schema AS schema,sequence_name AS name FROM information_schema.sequences
    WHERE sequence_schema NOT IN ('pg_catalog','information_schema')) x));"""


def _catalog_rows(rows: object) -> list[dict[str, str]]:
    _require(isinstance(rows, list) and len(rows) <= 64, "BACKUP_CATALOG_LIMIT")
    result = []
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"schema", "name"}, "BACKUP_CATALOG_INVALID")
        _require(
            all(isinstance(row[key], str) and IDENTIFIER.fullmatch(row[key]) for key in row),
            "BACKUP_CATALOG_IDENTIFIER",
        )
        result.append(row)
    _require(
        len({(r["schema"], r["name"]) for r in result}) == len(result), "BACKUP_CATALOG_DUPLICATE"
    )
    return result


class DockerBackupRuntime:
    def __init__(self, contract: dict) -> None:
        self.contract = contract
        _require(
            set(contract["containers"]) == SERVICES and set(contract["images"]) == SERVICES,
            "BACKUP_RUNTIME_CONTRACT",
        )
        _require(
            all(isinstance(v, str) and ID.fullmatch(v) for v in contract["containers"].values()),
            "BACKUP_RUNTIME_CONTRACT",
        )
        _require(
            len(set(contract["containers"].values())) == len(SERVICES), "BACKUP_RUNTIME_CONTRACT"
        )
        self.pg = contract["containers"]["postgres"]
        self.cli = _OwnedCLI()
        self.remote_exec_unknown = False

    def _docker(self, args: list[str], **kwargs: object) -> bytes:
        _require(not self.remote_exec_unknown, "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN")
        try:
            return self.cli.run(["docker", "--context", "colima", *args], **kwargs)  # type: ignore[arg-type]
        except BaseException:
            # Killing/waiting the client does not stop an in-container exec.
            # No automatic query/retry: the maintenance owner must reconcile it.
            if args and args[0] == "exec":
                self.remote_exec_unknown = True
            raise

    def _exec(self) -> list[str]:
        args = ["exec", "--user", "postgres", self.pg, "/usr/bin/env"]
        # Empty PGSERVICEFILE is still a filename for libpq. Remove inherited
        # routing/auth variables before re-establishing the two fixed settings.
        for variable in (
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGPASSWORD",
            "PGHOST",
            "PGPORT",
            "PGUSER",
            "PGDATABASE",
        ):
            args.extend(["-u", variable])
        return [*args, READ_ONLY, "PGPASSFILE=/dev/null"]

    def assert_quiescent(self) -> None:
        contract = self.contract
        daemon = self._docker(["info", "--format", "{{.ID}}"]).decode().strip()
        _require(daemon == contract["daemon_id"], "BACKUP_DAEMON_IDENTITY_DRIFT")
        ids = (
            self._docker(
                [
                    "ps",
                    "-a",
                    "--no-trunc",
                    "--filter",
                    "label=com.docker.compose.project=" + contract["compose_project"],
                    "--format",
                    "{{.ID}}",
                ]
            )
            .decode()
            .splitlines()
        )
        expected = contract["containers"]
        _require(
            len(ids) == len(SERVICES) and set(ids) == set(expected.values()),
            "BACKUP_CONTAINER_SET_DRIFT",
        )
        payload = self._docker(["inspect", "--format", INSPECT, *expected.values()])
        rows = [json.loads(line) for line in payload.splitlines()]
        _require(len(rows) == len(SERVICES), "BACKUP_CONTAINER_IDENTITY_DRIFT")
        seen = set()
        for row in rows:
            role = row.get("Service")
            _require(
                role in SERVICES
                and role not in seen
                and row.get("Id") == expected[role]
                and row.get("Image") == contract["images"][role]
                and row.get("Owner") == contract["owner"]
                and row.get("Project") == contract["compose_project"],
                "BACKUP_CONTAINER_IDENTITY_DRIFT",
            )
            seen.add(role)
            state = row.get("State", {})
            if role in WRITERS:
                _require(
                    state.get("Running") is False and state.get("Status") in {"exited", "created"},
                    "BACKUP_WRITER_STILL_RUNNING",
                )
            elif role == "postgres":
                _require(
                    state.get("Running") is True and state.get("Status") == "running",
                    "BACKUP_POSTGRES_NOT_RUNNING",
                )
            mounts = [m for m in row.get("Mounts", []) if m.get("Destination") == "/artifacts"]
            _require(
                (len(mounts) == 1 if role in ARTIFACT_WRITERS else len(mounts) <= 1)
                and all(
                    m.get("Type") == "bind" and m.get("Source") == contract["source"]
                    for m in mounts
                ),
                "BACKUP_ARTIFACT_MOUNT_DRIFT",
            )

    def _sql(self, query: str) -> str:
        args = [
            *self._exec(),
            "psql",
            "--host=/var/run/postgresql",
            "--port=5432",
            "-X",
            "-A",
            "-t",
            "--no-password",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "motif_forge",
            "-d",
            "motif_forge",
            "-c",
            query,
        ]
        return self._docker(args).decode("utf-8").strip()

    def snapshot(self) -> dict:
        meta = json.loads(self._sql(CATALOG))
        _require(meta.get("database") == "motif_forge", "BACKUP_DATABASE_MISMATCH")
        _require(
            type(meta.get("db_bytes")) is int and 0 < meta["db_bytes"] <= MAX_DB_BYTES,
            "BACKUP_DATABASE_BUDGET",
        )
        _require(
            meta.get("schema_revision") == [self.contract["expected_db_revision"]],
            "BACKUP_SCHEMA_MISMATCH",
        )
        _require(
            type(meta.get("sessions")) is int and meta["sessions"] == 0,
            "BACKUP_OTHER_DATABASE_SESSIONS",
        )
        tables, sequences = _catalog_rows(meta["tables"]), _catalog_rows(meta["sequences"])
        _require(bool(tables), "BACKUP_CATALOG_EMPTY")
        table_sql = []
        for row in tables:
            schema, table = row["schema"], row["name"]
            table_sql.append(
                f"SELECT json_build_object('schema','{schema}','table','{table}','rows',count(*),"
                "'digest',md5(coalesce(string_agg(md5(row_to_json(t)::text),'' "
                f'ORDER BY md5(row_to_json(t)::text)),\'\'))) FROM "{schema}"."{table}" t'
            )
        table_rows = [
            json.loads(line) for line in self._sql(" UNION ALL ".join(table_sql)).splitlines()
        ]
        _require(len(table_rows) == len(tables), "BACKUP_TABLE_SUMMARY_INVALID")
        for row, expected in zip(table_rows, tables, strict=True):
            _require(
                row.get("schema") == expected["schema"]
                and row.get("table") == expected["name"]
                and type(row.get("rows")) is int
                and row["rows"] >= 0
                and isinstance(row.get("digest"), str)
                and ROW_DIGEST.fullmatch(row["digest"]),
                "BACKUP_TABLE_SUMMARY_INVALID",
            )
        sequence_rows = []
        if sequences:
            queries = [
                f"SELECT json_build_object('schema','{r['schema']}','sequence','{r['name']}',"
                "'last_value',last_value,'is_called',is_called) FROM "
                f'"{r["schema"]}"."{r["name"]}"'
                for r in sequences
            ]
            sequence_rows = [
                json.loads(line) for line in self._sql(" UNION ALL ".join(queries)).splitlines()
            ]
            _require(len(sequence_rows) == len(sequences), "BACKUP_SEQUENCE_SUMMARY_INVALID")
            for row, expected in zip(sequence_rows, sequences, strict=True):
                _require(
                    row.get("schema") == expected["schema"]
                    and row.get("sequence") == expected["name"]
                    and type(row.get("last_value")) is int
                    and type(row.get("is_called")) is bool,
                    "BACKUP_SEQUENCE_SUMMARY_INVALID",
                )
        return {
            "database": "motif_forge",
            "schema_revision": self.contract["expected_db_revision"],
            "tables": table_rows,
            "sequences": sequence_rows,
        }

    def dump(self, binary_file: BinaryIO, max_bytes: int) -> None:
        _require(type(max_bytes) is int and 0 < max_bytes <= MAX_DB_BYTES, "BACKUP_DUMP_BUDGET")
        _require(binary_file.tell() == 0, "BACKUP_DUMP_TARGET_NOT_EMPTY")
        args = [
            *self._exec(),
            "pg_dump",
            "--host=/var/run/postgresql",
            "--port=5432",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--no-password",
            "-U",
            "motif_forge",
            "-d",
            "motif_forge",
        ]
        header = self._docker(args, sink=binary_file, limit=max_bytes, timeout=120)
        _require(header == b"PGDMP", "BACKUP_DUMP_FORMAT")

    def close(self) -> None:
        self.cli.close()
        _require(not self.remote_exec_unknown, "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN")
