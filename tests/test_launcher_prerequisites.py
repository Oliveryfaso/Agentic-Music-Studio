"""Exercise the shell entry without Docker, private config or user data."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _run(tmp_path: Path, node: str, python: str, *args: str, with_vite: bool = False):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/start_motif_forge.sh", repo / "scripts")
    if with_vite:
        vite = repo / "node_modules/.bin/vite"
        vite.parent.mkdir(parents=True)
        vite.write_text('#!/bin/sh\necho vite >> "$CALL_LOG"\nexit 91\n')
        vite.chmod(0o755)
    commands = tmp_path / "commands"
    commands.mkdir()
    log = tmp_path / "calls.log"
    for name, version in (("node", node), ("python3", python)):
        command = commands / name
        command.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "--version" ]; then echo "{version}"; exit 0; fi\n'
            f'echo "{name} unexpected execution" >> "$CALL_LOG"\nexit 91\n'
        )
        command.chmod(0o755)
    docker = commands / "docker"
    docker.write_text('#!/bin/sh\necho docker >> "$CALL_LOG"\nexit 0\n')
    docker.chmod(0o755)
    for name in ("npm", "curl"):
        command = commands / name
        command.write_text(f'#!/bin/sh\necho {name} >> "$CALL_LOG"\nexit 91\n')
        command.chmod(0o755)
    storage = tmp_path / "storage"
    runtime = tmp_path / "runtime"
    result = subprocess.run(
        ["bash", str(repo / "scripts/start_motif_forge.sh"), *args],
        env={
            "PATH": f"{commands}:{os.environ['PATH']}",
            "CALL_LOG": str(log),
            "MOTIF_FORGE_DEV_STORAGE_ROOT": str(storage),
            "MOTIF_FORGE_RUNTIME_DIR": str(runtime),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert not (repo / ".env").exists()
    assert not runtime.exists()
    assert not runtime.with_name(runtime.name + "-personal-beta").exists()
    assert not storage.exists()
    assert not (repo / "artifacts").exists()
    return result, log


@pytest.mark.parametrize(
    ("node", "python", "message"),
    [
        ("v20.19.0", "Python 3.12.0", "Node.js 22.12+"),
        ("v22.11.0", "Python 3.12.0", "Node.js 22.12+"),
        ("v26.0.0", "Python 3.9.6", "Python 3.12-3.13"),
        ("v26.0.0", "Python 3.14.0", "Python 3.12-3.13"),
    ],
)
@pytest.mark.parametrize("args", [("--check",), ("--enable-deepseek", "--no-open")])
def test_unsupported_runtime_stops_before_config_storage_or_docker(
    tmp_path: Path, node: str, python: str, message: str, args: tuple[str, ...]
) -> None:
    result, log = _run(tmp_path, node, python, *args)
    assert result.returncode == 69
    assert message in result.stderr
    assert not log.exists(), "unsupported tools must not reach config or Docker"


@pytest.mark.parametrize(
    ("node", "python"), [("v22.12.0", "Python 3.12.0"), ("v26.0.0", "Python 3.13.1")]
)
def test_supported_runtime_reaches_nonmutating_missing_configuration_diagnostic(
    tmp_path: Path, node: str, python: str
) -> None:
    result, log = _run(tmp_path, node, python, "--check", with_vite=True)
    assert result.returncode == 78
    assert "missing .env" in result.stderr
    assert log.read_text() == "docker\n"


@pytest.mark.parametrize(
    "args",
    [
        ("--check",),
        ("--no-open",),
        ("--enable-deepseek", "--no-open"),
        ("--personal-beta", "--check"),
        ("--personal-beta", "--no-open"),
        ("--personal-beta", "--enable-deepseek", "--no-open"),
    ],
)
def test_missing_vite_stops_before_key_config_storage_or_external_commands(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    result, log = _run(tmp_path, "v22.12.0", "Python 3.12.0", *args, with_vite=False)
    assert result.returncode == 69
    assert "npm ci" in result.stderr
    assert not log.exists(), "missing Web dependencies must stop before Key checks or external work"


def test_help_does_not_require_supported_tool_versions(tmp_path: Path) -> None:
    result, log = _run(tmp_path, "invalid", "invalid", "--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert not log.exists()
