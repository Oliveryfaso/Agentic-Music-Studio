"""Owned stdin accepts only a bounded regular file and retains process wait gates."""

import hashlib
import json
import os
import sys

import pytest

from scripts import personal_beta_backup_runtime as runtime

PRIVATE = "SYNTHETIC_PRIVATE_STDIN_SOURCE"
PAYLOAD = b"PGDMP\x00\xff\x80\n" + bytes(range(256)) * 4097
READ_DIGEST = (
    "import hashlib,json,sys; data=sys.stdin.buffer.read(); "
    "print(json.dumps({'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}))"
)


def test_regular_stdin_transfers_every_binary_byte_and_keeps_caller_file_open(tmp_path):
    path = tmp_path / PRIVATE
    path.write_bytes(PAYLOAD)
    cli = runtime._OwnedCLI()
    try:
        with path.open("rb") as source:
            output = cli.run([sys.executable, "-B", "-c", READ_DIGEST], stdin_file=source)
            assert json.loads(output) == {
                "bytes": len(PAYLOAD),
                "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            }
            assert not source.closed
            source.seek(0)
            assert source.read(9) == PAYLOAD[:9]
        assert len(cli.children) == 1
        assert cli.children[0].returncode == 0
        assert cli.children[0].backup_waited is True
    finally:
        cli.close()


def test_omitted_stdin_still_reads_eof_from_devnull():
    cli = runtime._OwnedCLI()
    try:
        output = cli.run([sys.executable, "-B", "-c", READ_DIGEST])
        assert json.loads(output) == {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        assert cli.children[0].returncode == 0
        assert cli.children[0].backup_waited is True
    finally:
        cli.close()


@pytest.mark.parametrize("kind", ["closed", "nonregular", "oversize", "offset"])
def test_invalid_stdin_is_rejected_before_spawning(tmp_path, monkeypatch, kind):
    path = tmp_path / PRIVATE
    path.write_bytes(b"PGDMP\x00synthetic")
    if kind == "oversize":
        with path.open("wb") as sparse:
            sparse.truncate(64 * 1024**2 + 1)
    # Manual lifetime is intentional: exercise closed and caller-owned handles.
    source = open(os.devnull, "rb") if kind == "nonregular" else path.open("rb")  # noqa: SIM115
    if kind == "closed":
        source.close()
    elif kind == "offset":
        source.seek(1)
    spawned = []

    def forbidden_popen(*args, **kwargs):
        spawned.append(True)
        raise AssertionError("invalid stdin reached process creation")

    monkeypatch.setattr(runtime.subprocess, "Popen", forbidden_popen)
    cli = runtime._OwnedCLI()
    try:
        with pytest.raises(RuntimeError) as caught:
            cli.run([sys.executable, "-B", "-c", "pass"], stdin_file=source)
        assert str(caught.value) == "BACKUP_STDIN_INVALID"
        assert PRIVATE not in str(caught.value)
        assert spawned == []
        assert cli.children == []
        if kind != "closed":
            assert not source.closed
    finally:
        source.close()
        cli.close()


def test_stdin_preserves_output_timeout_and_nonzero_exit_wait_protection(tmp_path):
    path = tmp_path / PRIVATE
    path.write_bytes(PAYLOAD[:4096])
    cases = [
        (
            "import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b'x'*100)",
            {"limit": 8},
            "BACKUP_OUTPUT_LIMIT",
        ),
        (
            "import sys,time;sys.stdin.buffer.read();time.sleep(2)",
            {"timeout": 0.03},
            "BACKUP_CLI_TIMEOUT",
        ),
        (
            "import sys;sys.stdin.buffer.read();sys.stderr.write('" + PRIVATE + "');sys.exit(3)",
            {},
            "BACKUP_CLI_FAILED",
        ),
    ]
    for code, options, expected in cases:
        cli = runtime._OwnedCLI()
        try:
            with path.open("rb") as source:
                with pytest.raises(RuntimeError) as caught:
                    cli.run([sys.executable, "-B", "-c", code], stdin_file=source, **options)
                assert str(caught.value) == expected
                assert PRIVATE not in str(caught.value)
                assert not source.closed
            assert len(cli.children) == 1
            assert cli.children[0].returncode is not None
            assert cli.children[0].backup_waited is True
        finally:
            cli.close()
