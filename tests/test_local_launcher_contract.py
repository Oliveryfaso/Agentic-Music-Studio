from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "scripts" / "start_motif_forge.sh"
STOPPER = ROOT / "scripts" / "stop_motif_forge.sh"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def test_launcher_exposes_safe_one_command_contract() -> None:
    assert LAUNCHER.is_file(), "the one-command launcher must exist"
    source = LAUNCHER.read_text(encoding="utf-8")

    for required in (
        "set -euo pipefail",
        "--check",
        "--no-open",
        "MOTIF_FORGE_DEV_STORAGE_ROOT",
        "bootstrap_external_storage.sh",
        "colima start",
        "docker compose up -d",
        "/health/ready",
        "http://127.0.0.1:8090/health",
        "npm run dev:web",
    ):
        assert required in source

    for forbidden in (
        "local attempts=45",
        "docker system prune",
        "docker image prune",
        "docker volume prune",
        "docker compose down -v",
        "DEEPSEEK_API_KEY=",
    ):
        assert forbidden not in source

    assert "local deadline=$((SECONDS + 60))" in source


def test_launcher_help_is_valid_without_starting_services() -> None:
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--check" in result.stdout
    assert "--no-open" in result.stdout


def test_stopper_shuts_down_owned_web_compose_and_colima_without_deleting_data(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    web_stopped_marker = tmp_path / "web.stopped"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    fake_npm = fake_bin / "npm"
    _write_executable(
        fake_npm,
        """#!/usr/bin/env bash
trap 'touch "$MOTIF_FORGE_TEST_WEB_STOPPED"; exit 0' TERM
while true; do :; done
""",
    )
    _write_executable(
        fake_bin / "ps",
        """#!/usr/bin/env bash
if [[ "$*" == *"stat="* ]]; then
  if [[ -f "$MOTIF_FORGE_TEST_WEB_STOPPED" ]]; then printf 'Z\\n'; else printf 'S\\n'; fi
  exit 0
fi
printf 'npm run dev:web -- --host 127.0.0.1\\n'
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
if [[ "$1" == "info" ]]; then exit 0; fi
printf 'docker %s\\n' "$*" >> "$MOTIF_FORGE_TEST_COMMAND_LOG"
""",
    )
    _write_executable(
        fake_bin / "colima",
        """#!/usr/bin/env bash
if [[ "$1" == "status" ]]; then exit 0; fi
printf 'colima %s\\n' "$*" >> "$MOTIF_FORGE_TEST_COMMAND_LOG"
""",
    )

    web_process = subprocess.Popen(
        [str(fake_npm), "run", "dev:web", "--", "--host", "127.0.0.1"],
        start_new_session=True,
    )
    (runtime_dir / "web.pid").write_text(
        f"{web_process.pid}\n{ROOT}\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "MOTIF_FORGE_RUNTIME_DIR": str(runtime_dir),
        "MOTIF_FORGE_TEST_COMMAND_LOG": str(command_log),
        "MOTIF_FORGE_TEST_WEB_STOPPED": str(web_stopped_marker),
    }

    try:
        result = subprocess.run(
            ["bash", str(STOPPER)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        if result.returncode == 0:
            assert "Stopping Motif Forge Web Studio" in result.stdout
            web_process.wait(timeout=5)
    finally:
        if web_process.poll() is None:
            os.killpg(web_process.pid, signal.SIGTERM)
            web_process.wait(timeout=5)

    assert result.returncode == 0, result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "docker compose down",
        "colima stop",
    ]
    assert not (runtime_dir / "web.pid").exists()


def test_stopper_discards_stale_pid_without_killing_an_unrelated_process(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _write_executable(fake_bin / "docker", "#!/usr/bin/env bash\nexit 1\n")
    _write_executable(fake_bin / "colima", "#!/usr/bin/env bash\nexit 1\n")

    unrelated_process = subprocess.Popen(["sleep", "60"])
    (runtime_dir / "web.pid").write_text(
        f"{unrelated_process.pid}\n{ROOT}\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "MOTIF_FORGE_RUNTIME_DIR": str(runtime_dir),
    }

    try:
        result = subprocess.run(
            ["bash", str(STOPPER)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert unrelated_process.poll() is None
    finally:
        unrelated_process.terminate()
        unrelated_process.wait(timeout=5)

    assert result.returncode == 0, result.stderr
    assert not (runtime_dir / "web.pid").exists()


def test_readme_leads_with_one_command_launch_and_current_product_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    launcher_position = readme.index("scripts/start_motif_forge.sh")
    stopper_position = readme.index("scripts/stop_motif_forge.sh")
    prerequisites_position = readme.index("## Prerequisites")
    assert launcher_position < prerequisites_position
    assert stopper_position < prerequisites_position
    assert "S1\u2013S7" in readme[:prerequisites_position]
    assert "remain later stages" not in readme[:prerequisites_position]
