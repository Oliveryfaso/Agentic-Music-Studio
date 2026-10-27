"""Read-only adapter contracts: synthetic responses and owned Python processes.

No Docker daemon, network, source DB, existing credential or user media access.
"""

import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys

import pytest

SERVICES = (
    "api",
    "dispatcher",
    "resume-dispatcher",
    "media-worker",
    "render-worker",
    "migrate",
    "storage-init",
    "postgres",
    "redis",
)


def test_explicit_backup_has_read_only_runtime_adapter():
    assert importlib.util.find_spec("scripts.personal_beta_backup_runtime"), (
        "explicit backup has no read-only Docker runtime adapter"
    )


@pytest.fixture
def module():
    assert importlib.util.find_spec("scripts.personal_beta_backup_runtime"), (
        "explicit backup has no read-only Docker runtime adapter"
    )
    return importlib.import_module("scripts.personal_beta_backup_runtime")


@pytest.fixture
def contract():
    return {
        "daemon_id": "synthetic-daemon",
        "compose_project": "motif-test",
        "owner": "12345678-1234-1234-1234-123456789012",
        "source": "/synthetic/artifacts",
        "expected_db_revision": "20261020_0030",
        "containers": {
            service: format(index + 1, "064x") for index, service in enumerate(SERVICES)
        },
        "images": {service: "sha256:" + "a" * 64 for service in SERVICES},
    }


def container_rows(contract):
    rows = []
    for service in SERVICES:
        running = service in {"postgres", "redis"}
        rows.append(
            {
                "Id": contract["containers"][service],
                "Image": contract["images"][service],
                "Project": contract["compose_project"],
                "Owner": contract["owner"],
                "Service": service,
                "State": {"Running": running, "Status": "running" if running else "exited"},
                "Mounts": []
                if service in {"postgres", "redis", "migrate", "dispatcher"}
                else [{"Destination": "/artifacts", "Source": contract["source"], "Type": "bind"}],
            }
        )
    return rows


def stub_inspection(monkeypatch, runtime, contract, rows=None, ids=None, daemon=None):
    calls = []
    responses = [
        (daemon or contract["daemon_id"]).encode(),
        ("\n".join(ids or contract["containers"].values()) + "\n").encode(),
        ("\n".join(json.dumps(row) for row in (rows or container_rows(contract))) + "\n").encode(),
    ]

    def command(args, **kwargs):
        calls.append(args)
        return responses.pop(0)

    monkeypatch.setattr(runtime, "_docker", command)
    return calls


def test_quiescent_identity_and_stopped_writers_pass(module, contract, monkeypatch):
    runtime = module.DockerBackupRuntime(contract)
    calls = stub_inspection(monkeypatch, runtime, contract)
    runtime.assert_quiescent()
    assert [c[0] for c in calls] == ["info", "ps", "inspect"]
    inspect = calls[-1]
    assert ".Config.Env" not in " ".join(inspect)
    assert set(inspect[inspect.index("--format") + 2 :]) == set(contract["containers"].values())
    assert not any(x in {"start", "stop", "rm", "pull", "run", "create"} for c in calls for x in c)


@pytest.mark.parametrize("service", SERVICES[:7])
def test_every_writer_must_be_exited(module, contract, monkeypatch, service):
    runtime = module.DockerBackupRuntime(contract)
    rows = container_rows(contract)
    row = next(x for x in rows if x["Service"] == service)
    row["State"] = {"Running": True, "Status": "running"}
    stub_inspection(monkeypatch, runtime, contract, rows)
    with pytest.raises(RuntimeError, match="WRITER"):
        runtime.assert_quiescent()


@pytest.mark.parametrize(
    "field,value", [("Image", "sha256:" + "f" * 64), ("Owner", "foreign"), ("Service", "other")]
)
def test_identity_drift_rejected(module, contract, monkeypatch, field, value):
    runtime = module.DockerBackupRuntime(contract)
    rows = container_rows(contract)
    rows[0][field] = value
    stub_inspection(monkeypatch, runtime, contract, rows)
    with pytest.raises(RuntimeError, match="IDENTITY"):
        runtime.assert_quiescent()


def test_unknown_project_container_rejected(module, contract, monkeypatch):
    runtime = module.DockerBackupRuntime(contract)
    calls = stub_inspection(
        monkeypatch, runtime, contract, ids=[*contract["containers"].values(), "f" * 64]
    )
    with pytest.raises(RuntimeError, match="CONTAINER_SET"):
        runtime.assert_quiescent()
    assert len(calls) == 2


def test_foreign_artifact_mount_rejected(module, contract, monkeypatch):
    runtime = module.DockerBackupRuntime(contract)
    rows = container_rows(contract)
    rows[0]["Mounts"][0]["Source"] = "/synthetic/other"
    stub_inspection(monkeypatch, runtime, contract, rows)
    with pytest.raises(RuntimeError, match="MOUNT"):
        runtime.assert_quiescent()


def metadata():
    return {
        "database": "motif_forge",
        "db_bytes": 2048,
        "sessions": 0,
        "schema_revision": ["20261020_0030"],
        "tables": [
            {"schema": "public", "name": "alembic_version"},
            {"schema": "app", "name": "projects"},
        ],
        "sequences": [{"schema": "app", "name": "events_id_seq"}],
    }


TABLE_ROWS = [
    {"schema": "public", "table": "alembic_version", "rows": 1, "digest": "a" * 32},
    {"schema": "app", "table": "projects", "rows": 2, "digest": "b" * 32},
]
SEQUENCE_ROWS = [{"schema": "app", "sequence": "events_id_seq", "last_value": 4, "is_called": True}]


def stub_snapshot(monkeypatch, runtime, meta=None):
    queries = []
    responses = [
        json.dumps(metadata() if meta is None else meta),
        "\n".join(json.dumps(row) for row in TABLE_ROWS),
        "\n".join(json.dumps(row) for row in SEQUENCE_ROWS),
    ]

    def sql(query):
        queries.append(query)
        return responses.pop(0)

    monkeypatch.setattr(runtime, "_sql", sql)
    return queries


def test_snapshot_includes_all_table_hashes_and_sequence_states(module, contract, monkeypatch):
    runtime = module.DockerBackupRuntime(contract)
    queries = stub_snapshot(monkeypatch, runtime)
    result = runtime.snapshot()
    assert result == {
        "database": "motif_forge",
        "schema_revision": "20261020_0030",
        "tables": TABLE_ROWS,
        "sequences": SEQUENCE_ROWS,
    }
    assert "UNION ALL" in queries[1] and '"app"."projects"' in queries[1]
    assert "last_value" in queries[2] and "is_called" in queries[2]
    assert all("INSERT" not in q and "CREATE" not in q and "UPDATE" not in q for q in queries)


@pytest.mark.parametrize(
    "field,value",
    [
        ("database", "other"),
        ("schema_revision", ["20261024_0031"]),
        ("sessions", 1),
        ("db_bytes", 64 * 1024**2 + 1),
    ],
)
def test_snapshot_refuses_other_db_revision_live_session_or_oversize(
    module, contract, monkeypatch, field, value
):
    runtime = module.DockerBackupRuntime(contract)
    meta = metadata()
    meta[field] = value
    queries = stub_snapshot(monkeypatch, runtime, meta)
    with pytest.raises(RuntimeError):
        runtime.snapshot()
    assert len(queries) == 1


def test_catalog_sql_injection_rejected_before_dynamic_query(module, contract, monkeypatch):
    runtime = module.DockerBackupRuntime(contract)
    meta = metadata()
    meta["tables"][0]["name"] = "x;drop table app.projects"
    queries = stub_snapshot(monkeypatch, runtime, meta)
    with pytest.raises(RuntimeError, match="CATALOG"):
        runtime.snapshot()
    assert len(queries) == 1


def test_psql_uses_read_only_local_socket_and_no_credentials(module, contract, monkeypatch):
    runtime = module.DockerBackupRuntime(contract)
    calls = []
    monkeypatch.setattr(runtime, "_docker", lambda args, **kw: calls.append(args) or b"{}\n")
    runtime._sql("SELECT 1")
    args = calls[0]
    assert args[:3] == ["exec", "--user", "postgres"]
    assert "PGOPTIONS=-c default_transaction_read_only=on" in args
    assert "--no-password" in args and "-X" in args and "ON_ERROR_STOP=1" in args
    assert contract["containers"]["postgres"] in args
    assert not any(
        ("password=" in arg.lower() and arg != "PGPASSWORD=") or "://" in arg for arg in args
    )


def test_dump_streams_binary_and_uses_read_only_custom_format(module, contract, monkeypatch):
    runtime = module.DockerBackupRuntime(contract)
    payload = b"PGDMP\x00\xff\x80\n"
    calls = []

    def docker(args, **kwargs):
        calls.append((args, kwargs))
        kwargs["sink"].write(payload)
        return payload[:5]

    monkeypatch.setattr(runtime, "_docker", docker)
    target = io.BytesIO()
    runtime.dump(target, 1024)
    assert target.getvalue() == payload
    args, options = calls[0]
    assert "pg_dump" in args and "--format=custom" in args and "--no-owner" in args
    assert "PGOPTIONS=-c default_transaction_read_only=on" in args
    assert options["limit"] == 1024


@pytest.mark.parametrize("operation", ["sql", "dump"])
def test_container_libpq_environment_cannot_redirect_or_read_old_credentials(
    module, contract, monkeypatch, operation
):
    runtime = module.DockerBackupRuntime(contract)
    calls = []
    monkeypatch.setattr(runtime, "_docker", lambda args, **kwargs: calls.append(args) or b"PGDMP")
    if operation == "sql":
        runtime._sql("SELECT 1")
    else:
        runtime.dump(io.BytesIO(), 1024)
    args = calls[0]
    assert "--host=/var/run/postgresql" in args and "--port=5432" in args
    assert args[:4] == ["exec", "--user", "postgres", runtime.pg]
    inner = args[4:]
    assert inner[0] == "/usr/bin/env"
    for variable in ("PGPASSWORD", "PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR"):
        assert any(
            pair == ["-u", variable] for pair in (inner[i : i + 2] for i in range(len(inner) - 1))
        )
    assert "PGPASSFILE=/dev/null" in inner
    assert "PGOPTIONS=-c default_transaction_read_only=on" in inner
    assert not any(value in inner for value in ("PGSERVICE=", "PGSERVICEFILE="))


def env_prefix(runtime):
    args = runtime._exec()
    prefix = args[args.index(runtime.pg) + 1 :]
    assert prefix and prefix[0] == "/usr/bin/env"
    return prefix


def test_real_env_process_removes_poison_instead_of_assigning_empty(module, contract):
    runtime = module.DockerBackupRuntime(contract)
    variables = (
        "PGPASSWORD",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGHOSTADDR",
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGDATABASE",
    )
    code = (
        "import os,json; names=" + repr(variables) + "; print(json.dumps({"
        "'absent':all(name not in os.environ for name in names),"
        "'readonly':os.environ.get('PGOPTIONS')=='-c default_transaction_read_only=on',"
        "'passfile':os.environ.get('PGPASSFILE')=='/dev/null'}))"
    )
    poison = dict.fromkeys(variables, "SYNTHETIC_POISON")
    poison["PGPASSFILE"] = "/synthetic/not-read"
    poison["PGOPTIONS"] = "SYNTHETIC_WRITABLE"
    result = subprocess.run(
        [*env_prefix(runtime), sys.executable, "-B", "-c", code],
        env=poison,
        capture_output=True,
        timeout=5,
        check=True,
    )
    assert result.stderr == b""
    assert json.loads(result.stdout) == {"absent": True, "readonly": True, "passfile": True}


def test_real_libpq_empty_servicefile_fails_before_nonexistent_socket_but_unset_reaches_socket(
    module, contract, tmp_path
):
    runtime = module.DockerBackupRuntime(contract)
    # This nonexistent, short Unix path cannot reach a TCP service or real DB.
    # No password/service file is read: legacy form attempts only path="";
    # repaired form has no service and passfile explicitly /dev/null.
    socket_path = "/tmp/motif-backup-no-socket-" + tmp_path.name[-12:]
    assert not os.path.exists(socket_path)
    conninfo = (
        "host=" + socket_path + " port=5432 user=motif_synthetic dbname=motif_synthetic "
        "connect_timeout=1 passfile=/dev/null"
    )
    code = (
        "import json; from psycopg import pq; c=pq.PGconn.connect(" + repr(conninfo.encode()) + ");"
        "e=c.error_message.lower();print(json.dumps({'bad':c.status==pq.ConnStatus.BAD,"
        "'service_file':b'service file' in e,"
        "'local_missing':b'socket' in e and b'no such file' in e}));c.finish()"
    )
    legacy = subprocess.run(
        [
            "/usr/bin/env",
            "PGSERVICE=",
            "PGSERVICEFILE=",
            "PGHOSTADDR=",
            "PGPASSWORD=",
            "PGPASSFILE=/dev/null",
            sys.executable,
            "-B",
            "-c",
            code,
        ],
        env={},
        capture_output=True,
        timeout=5,
        check=True,
    )
    assert legacy.stderr == b""
    assert json.loads(legacy.stdout) == {"bad": True, "service_file": True, "local_missing": False}
    clean = subprocess.run(
        [*env_prefix(runtime), sys.executable, "-B", "-c", code],
        env={
            "PGSERVICE": "SYNTHETIC_POISON",
            "PGSERVICEFILE": "SYNTHETIC_NOT_READ",
            "PGPASSWORD": "SYNTHETIC_POISON",
        },
        capture_output=True,
        timeout=5,
        check=True,
    )
    # libpq18 warns when explicitly denying a password file via /dev/null.
    # This is not the service-file failure and does not cause another path read.
    assert clean.stderr in (
        b"",
        b'WARNING: password file "/dev/null" is not a plain file\n',
    )
    assert json.loads(clean.stdout) == {"bad": True, "service_file": False, "local_missing": True}


@pytest.mark.parametrize(
    "message,code",
    [
        (b'service file "SYNTHETIC_PATH" not found', "BACKUP_CLI_SERVICE_FILE_ERROR"),
        (
            b'connection to server on socket "SYNTHETIC_PATH" failed: No such file or directory',
            "BACKUP_CLI_LOCAL_SOCKET_UNAVAILABLE",
        ),
    ],
)
def test_cli_failure_reports_only_safe_classification(module, message, code):
    cli = module._OwnedCLI()
    try:
        with pytest.raises(RuntimeError) as failed:
            cli.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import os;os.write(2," + repr(message) + ");raise SystemExit(2)",
                ]
            )
        assert str(failed.value) == code
        assert "SYNTHETIC_PATH" not in str(failed.value)
    finally:
        cli.close()


def test_unconfirmed_exec_blocks_close_even_when_host_cli_wait_is_proven(
    module, contract, monkeypatch
):
    runtime = module.DockerBackupRuntime(contract)

    def failed_cli(_argv, **_kwargs):
        raise module.BackupRuntimeError("BACKUP_CLI_TIMEOUT")

    monkeypatch.setattr(runtime.cli, "run", failed_cli)
    monkeypatch.setattr(runtime.cli, "close", lambda: None)
    with pytest.raises(RuntimeError, match="TIMEOUT"):
        runtime._sql("SELECT 1")
    with pytest.raises(RuntimeError, match="REMOTE_EXEC_EXIT_UNKNOWN"):
        runtime._sql("SELECT 2")
    with pytest.raises(RuntimeError, match="REMOTE_EXEC_EXIT_UNKNOWN"):
        runtime.close()


@pytest.mark.parametrize(
    "service", ["api", "storage-init", "resume-dispatcher", "media-worker", "render-worker"]
)
def test_each_artifact_writer_requires_its_exact_source_bind(
    module, contract, monkeypatch, service
):
    runtime = module.DockerBackupRuntime(contract)
    rows = container_rows(contract)
    row = next(item for item in rows if item["Service"] == service)
    row["Mounts"] = []
    stub_inspection(monkeypatch, runtime, contract, rows)
    with pytest.raises(RuntimeError, match="MOUNT"):
        runtime.assert_quiescent()


def test_owned_cli_raw_binary_and_streaming_hard_limit(module):
    cli = module._OwnedCLI()
    payload = b"PGDMP\x00\xff\x80\n"
    try:
        out = io.BytesIO()
        header = cli.run(
            [sys.executable, "-c", "import os;os.write(1," + repr(payload) + ")"],
            sink=out,
            limit=1024,
        )
        assert out.getvalue() == payload and header == payload[:5]
        assert cli.run([sys.executable, "-c", "print('ok')"]) == b"ok\n"
        out = io.BytesIO()
        with pytest.raises(RuntimeError, match="OUTPUT"):
            cli.run([sys.executable, "-c", "import os;os.write(1,b'x'*100)"], sink=out, limit=8)
        assert len(out.getvalue()) <= 8
    finally:
        cli.close()


def test_owned_cli_failure_and_timeout_do_not_expose_stderr_or_argv(module):
    cli = module._OwnedCLI()
    try:
        with pytest.raises(RuntimeError) as failed:
            cli.run(
                [
                    sys.executable,
                    "-c",
                    "import sys;sys.stderr.write('SYNTHETIC_PRIVATE');sys.exit(3)",
                ]
            )
        assert "SYNTHETIC_PRIVATE" not in str(failed.value)
        with pytest.raises(RuntimeError, match="TIMEOUT"):
            cli.run([sys.executable, "-c", "import time;time.sleep(2)"], timeout=0.03)
        assert all(child.returncode is not None for child in cli.children)
    finally:
        cli.close()


def test_group_permission_unknown_blocks_future_cli(module, monkeypatch):
    cli = module._OwnedCLI()
    original = os.killpg
    try:

        def refuse_probe(pid, signum):
            if signum == 0:
                raise PermissionError
            return original(pid, signum)

        with monkeypatch.context() as patch:
            patch.setattr(module.os, "killpg", refuse_probe)
            with pytest.raises(RuntimeError, match="EXIT_UNKNOWN"):
                cli.run([sys.executable, "-c", "pass"])
        with pytest.raises(RuntimeError, match="EXIT_UNKNOWN"):
            cli.run([sys.executable, "-c", "pass"])
        with pytest.raises(RuntimeError, match="EXIT_UNKNOWN"):
            cli.close()
    finally:
        # The exact leader is already waited; do not retry the refused group query.
        for child in cli.children:
            assert child.poll() is not None
