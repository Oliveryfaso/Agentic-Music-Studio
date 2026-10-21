from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PYTHON = Path(sys.executable)


def executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def checkout(tmp_path: Path, *, vite: bool = True):
    repo = tmp_path / "checkout"
    repo.mkdir()
    for relative in (
        "compose.yaml",
        "compose.personal-beta.yaml",
        ".env.example",
        "scripts/start_motif_forge.sh",
        "scripts/stop_motif_forge.sh",
        "scripts/motif_runtime_lock.py",
        "scripts/build_compose_images.sh",
    ):
        source = ROOT / relative
        if source.exists():
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (repo / ".env").write_text("SYNTHETIC_POISON_ONLY=never-load\n")
    if vite:
        (repo / "node_modules/.bin").mkdir(parents=True)
        executable(repo / "node_modules/.bin/vite", "#!/bin/sh\nexit 0\n")
    executable(repo / "scripts/bootstrap_external_storage.sh", "#!/bin/sh\nexit 91\n")
    (repo / "scripts/personal_beta_preflight.py").write_text(
        "import os,sys\nimport beta_cache_probe\n"
        'sys.exit(int(os.environ.get("BETA_ASSET_EXIT","0")))\n'
    )
    (repo / "scripts/beta_cache_probe.py").write_text("VALUE = 1\n")
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    (bin_path / "python3").symlink_to(PYTHON)
    log = tmp_path / "commands.jsonl"
    executable(
        bin_path / "node",
        "#!"
        + str(PYTHON)
        + "\n"
        + """
import json,os,sys
from pathlib import Path
a=sys.argv[1:]
with open(os.environ['BETA_COMMAND_LOG'],'a') as f:
 f.write(json.dumps(['node',*a])+'\\n')
if len(a)>1 and a[1]=='init':
 p=Path(a[3]);p.mkdir(parents=True,exist_ok=True);p.chmod(0o700)
 (p/'operation.lock').touch(mode=0o600)
if len(a)>1 and a[1]=='prepare': print(a[4]+' synthetic-owner')
""",
    )
    executable(
        bin_path / "docker",
        "#!"
        + str(PYTHON)
        + "\n"
        + """
import json,os,sys
a=sys.argv[1:]
with open(os.environ['BETA_COMMAND_LOG'],'a') as f:
 f.write(json.dumps(['docker',*a])+'\\n')
if a and a[0]=='image' and os.environ.get('BETA_MISSING_IMAGE'): sys.exit(1)
if 'up' in a: sys.exit(42)
""",
    )
    executable(bin_path / "npm", "#!/bin/sh\nexit 92\n")
    executable(bin_path / "curl", "#!/bin/sh\nexit 93\n")
    storage = tmp_path / "storage"
    storage.mkdir()
    env = {
        "PATH": f"{bin_path}:{os.environ['PATH']}",
        "LANG": "C.UTF-8",
        "BETA_COMMAND_LOG": str(log),
        "MOTIF_FORGE_BETA_STORAGE_ROOT": str(storage),
        "MOTIF_FORGE_REVIEWED_PIANO_ROOT": str(tmp_path / "piano"),
        "MOTIF_FORGE_RUNTIME_DIR": str(tmp_path / "runtime"),
        "COMPOSE_FILE": str(tmp_path / "foreign-compose.yaml"),
        "COMPOSE_ENV_FILES": str(tmp_path / "foreign.env"),
        "LANGSMITH_API_KEY": "SYNTHETIC_SHELL_KEY",
        "LANGSMITH_TRACING": "true",
    }
    return repo, env, log


def launch(repo: Path, env: dict[str, str], *args: str):
    return subprocess.run(
        ["bash", str(repo / "scripts/start_motif_forge.sh"), "--personal-beta", *args],
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
    )


def calls(log: Path):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_beta_check_uses_explicit_public_config_without_writes(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    before = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    result = launch(repo, env, "--check")
    assert result.returncode == 0, result.stderr
    commands = calls(log)
    config = next(c for c in commands if "config" in c)
    assert "--env-file" in config and str(repo / ".env.example") in config
    assert config.count("-f") == 2 and str(repo / "compose.personal-beta.yaml") in config
    assert not any("up" in c or "init" in c or c[0] == "npm" for c in commands)
    after = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    assert after - before == {"commands.jsonl"}
    assert (repo / ".env").read_text() == "SYNTHETIC_POISON_ONLY=never-load\n"
    assert "SYNTHETIC" not in result.stdout + result.stderr


def test_beta_missing_vite_fails_without_install_or_start(tmp_path: Path):
    repo, env, log = checkout(tmp_path, vite=False)
    result = launch(repo, env, "--check")
    assert result.returncode == 69, result.stderr
    assert "Web dependencies" in result.stderr
    assert not any("up" in c or "init" in c or c[0] == "npm" for c in calls(log))


def test_beta_asset_rejection_prevents_up(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    env["BETA_ASSET_EXIT"] = "2"
    result = launch(repo, env, "--check")
    assert result.returncode == 78, result.stderr
    assert "resource" in result.stderr.lower()
    assert not any("up" in c for c in calls(log))


def test_beta_missing_image_requires_explicit_build(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    env["BETA_MISSING_IMAGE"] = "1"
    result = launch(repo, env, "--check")
    assert result.returncode == 78, result.stderr
    assert "build" in result.stderr.lower()
    assert not any("up" in c or "pull" in c or "build" in c for c in calls(log))


def test_beta_start_uses_no_build_and_never_pull(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    # Keep this test before any actual service boundary: the fake up exits42.
    executable(repo / "scripts/bootstrap_external_storage.sh", "#!/bin/sh\nexit 0\n")
    result = launch(repo, env, "--no-open")
    assert result.returncode == 42, result.stderr
    up = next(c for c in calls(log) if "up" in c)
    assert "--no-build" in up
    assert up[up.index("--pull") + 1] == "never"
    assert "--env-file" in up and up.count("-f") == 2
    prepare = next(c for c in calls(log) if "prepare" in c)
    assert prepare[-1].startswith("motif-forge-beta-")
    assert prepare[-2].endswith("-personal-beta")


def test_beta_stop_selects_the_same_isolated_runtime(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    result = subprocess.run(
        ["bash", str(repo / "scripts/stop_motif_forge.sh"), "--personal-beta"],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    stop = next(c for c in calls(log) if "stop" in c)
    assert stop[-1] == str(tmp_path / "runtime-personal-beta")


@pytest.mark.parametrize("port", ["0", "65536", "abc", "18000:8000", "01800"])
def test_beta_rejects_invalid_port_before_docker(tmp_path: Path, port: str):
    repo, env, log = checkout(tmp_path)
    env["MOTIF_FORGE_BETA_API_PORT"] = port
    result = launch(repo, env, "--check")
    assert result.returncode == 64, result.stderr
    assert "Invalid personal Beta port" in result.stderr
    assert not calls(log)


def test_real_compose_parser_proves_config_isolation_and_readonly_pin(tmp_path: Path):
    assert (ROOT / "compose.personal-beta.yaml").exists(), "personal Beta override is missing"
    docker = shutil.which("docker")
    assert docker, "Compose CLI is required for this no-daemon config boundary"
    repo, _, _ = checkout(tmp_path)
    env = {
        "PATH": os.environ["PATH"],
        "LANG": "C.UTF-8",
        "MOTIF_FORGE_CONTAINER_ENV_FILE": str(repo / ".env.example"),
        "MOTIF_FORGE_REVIEWED_PIANO_ROOT": str(tmp_path / "piano"),
        "MOTIF_FORGE_ARTIFACT_HOST_ROOT": str(tmp_path / "artifacts"),
        "MOTIF_FORGE_TEMP_ROOT": str(tmp_path / "scratch"),
        "MOTIF_FORGE_API_HOST_PORT": "18000",
        "MOTIF_FORGE_RENDER_HOST_PORT": "18090",
        "MOTIF_FORGE_POSTGRES_HOST_PORT": "15432",
        "MOTIF_FORGE_REDIS_HOST_PORT": "16379",
        "LANGSMITH_API_KEY": "SYNTHETIC_SHELL_KEY",
        "LANGSMITH_TRACING": "true",
        "DEEPSEEK_API_KEY": "SYNTHETIC_SHELL_MODEL_KEY",
        "COMPOSE_FILE": str(tmp_path / "missing-foreign-compose.yaml"),
        "COMPOSE_ENV_FILES": str(tmp_path / "missing-foreign.env"),
    }
    result = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            str(repo / ".env.example"),
            "-f",
            str(repo / "compose.yaml"),
            "-f",
            str(repo / "compose.personal-beta.yaml"),
            "--project-name",
            "motif-beta-config-test",
            "config",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert "SYNTHETIC_" not in result.stdout
    services = config["services"]
    expected_images = {
        "api": "api",
        "migrate": "api",
        "storage-init": "api",
        "dispatcher": "api",
        "resume-dispatcher": "api",
        "media-worker": "media-worker",
        "render-worker": "render-worker",
    }
    for name, image in expected_images.items():
        assert services[name]["image"] == f"motif-forge-beta-{image}:local"
        assert services[name]["environment"].get("DEEPSEEK_API_KEY", "") == ""
    for name in ("api", "migrate", "dispatcher", "resume-dispatcher", "media-worker"):
        values = services[name]["environment"]
        assert values["LANGSMITH_API_KEY"] == "" and values["LANGSMITH_TRACING"] == "false"
        assert values["MOTIF_FORGE_POSTGRES_DSN"].endswith("@postgres:5432/motif_forge")
    for service in services.values():
        assert all(port["host_ip"] == "127.0.0.1" for port in service.get("ports", []))
    for name in ("api", "resume-dispatcher", "media-worker"):
        assert (
            services[name]["environment"]["MOTIF_FORGE_RENDER_SERVICE_URL"]
            == "http://render-worker:8090"
        )
    renderer = services["render-worker"]
    mount = next(v for v in renderer["volumes"] if v["target"] == "/reviewed-piano")
    assert mount["read_only"] and mount.get("bind", {}).get("create_host_path") is False
    pin = json.loads((ROOT / "scripts/resource-contract.v1.json").read_text())["piano"][
        "manifest_sha256"
    ]
    assert renderer["environment"]["MOTIF_FORGE_REVIEWED_PIANO_MANIFEST_SHA256"] == pin
    assert (
        config["volumes"]["motif_forge_postgres"]["name"]
        == "motif-beta-config-test_motif_forge_postgres"
    )


@pytest.mark.parametrize("target", ["api", "media-worker", "render-worker"])
def test_beta_build_is_one_explicit_target_with_an_isolated_tag(tmp_path: Path, target: str):
    repo, env, log = checkout(tmp_path)
    executable(Path(env["PATH"].split(":")[0]) / "rsync", "#!/bin/sh\nexit 0\n")
    env["MOTIF_FORGE_BETA_IMAGE_TAG"] = "acceptance-1"
    result = subprocess.run(
        ["bash", str(repo / "scripts/build_compose_images.sh"), "--personal-beta", target],
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    builds = [c for c in calls(log) if c[:3] == ["docker", "buildx", "build"]]
    assert len(builds) == 1
    build = builds[0]
    assert build[build.index("--tag") + 1] == f"motif-forge-beta-{target}:acceptance-1"
    assert not any(arg.startswith("motif-forge-") and "-beta-" not in arg for arg in build)
    assert not Path(build[-1]).exists(), "owned clean context must be removed"


def test_beta_build_refuses_all_without_a_docker_call(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    result = subprocess.run(
        ["bash", str(repo / "scripts/build_compose_images.sh"), "--personal-beta", "all"],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 64
    assert not calls(log)


def test_legacy_single_target_build_retains_its_existing_tag(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    executable(Path(env["PATH"].split(":")[0]) / "rsync", "#!/bin/sh\nexit 0\n")
    result = subprocess.run(
        ["bash", str(repo / "scripts/build_compose_images.sh"), "api"],
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    builds = [c for c in calls(log) if c[:3] == ["docker", "buildx", "build"]]
    assert len(builds) == 1
    assert builds[0][builds[0].index("--tag") + 1] == "motif-forge-api:local"
