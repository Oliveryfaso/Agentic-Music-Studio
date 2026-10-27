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
RELEASE = json.loads((ROOT / "scripts/personal-beta-release.v1.json").read_text())


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
        "scripts/personal_beta_release.py",
        "scripts/personal-beta-release.v1.json",
    ):
        source = ROOT / relative
        if source.exists():
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    versions = repo / "infra/migrations/versions"
    versions.mkdir(parents=True)
    (versions / "head.py").write_text('revision="20261020_0030"\ndown_revision=None\n')
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
if a==['--version']: print('v22.12.0');sys.exit(0)
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
if a and a[0]=='image' and a[-1]==os.environ.get('BETA_MISSING_REF'): sys.exit(1)
if a and a[0]=='image':
 print(os.environ.get('BETA_API_IMAGE_ID','sha256:b133641886492ffeb3a73c3905beda303ad19d07319cb905ca0969841b6aa3d4'))
if 'config' in a and '--format' in a:
 selected=os.environ.get('MOTIF_FORGE_BETA_RELEASE_IMAGE_ID','motif-forge-beta-api:inspector-a3bfb1a')
 print(json.dumps({'services':{'api':{'image':os.environ.get('BETA_CONFIG_API_IMAGE',selected)},'migrate':{'image':os.environ.get('BETA_CONFIG_MIGRATE_IMAGE',selected)}}}))
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


@pytest.mark.parametrize("personal_beta", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_launcher_never_inherits_shell_key_or_overrides_checked_file(
    tmp_path: Path,
    personal_beta: bool,
    enabled: bool,
):
    repo, env, log = checkout(tmp_path)
    for relative in ("scripts/configure_deepseek.py", "compose.deepseek.yaml"):
        shutil.copy2(ROOT / relative, repo / relative)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    key_file = tmp_path / "config/motif-forge/deepseek.env"
    key_file.parent.mkdir(parents=True, mode=0o700)
    key_file.write_text("DEEPSEEK_API_KEY=sk-mock-private-A-0123456789\n")
    key_file.chmod(0o600)
    env["DEEPSEEK_API_KEY"] = "sk-mock-old-shell-B-9876543210"
    env["MOTIF_FORGE_DEV_STORAGE_ROOT"] = env["MOTIF_FORGE_BETA_STORAGE_ROOT"]
    docker = Path(env["PATH"].split(os.pathsep)[0]) / "docker"
    # Only synthetic files are read; record booleans, never the effective Key.
    probe = """
if 'config' in a:
 file_value=''
 for index,part in enumerate(a[:-1]):
  if part=='--env-file':
   with open(a[index+1]) as source:
    for line in source:
     if line.startswith('DEEPSEEK_API_KEY='): file_value=line.strip().split('=',1)[1]
 effective=os.environ.get('DEEPSEEK_API_KEY',file_value)
 with open(os.environ['BETA_COMMAND_LOG'],'a') as f:
  state=['deepseek-source','DEEPSEEK_API_KEY' in os.environ,
         effective=='sk-mock-private-A-0123456789']
  f.write(json.dumps(state)+'\\n')
"""
    docker.write_text(docker.read_text().replace("a=sys.argv[1:]", "a=sys.argv[1:]\n" + probe))
    args = ["--check"] + (["--enable-deepseek"] if enabled else [])
    if personal_beta:
        result = launch(repo, env, *args)
    else:
        result = subprocess.run(
            ["bash", str(repo / "scripts/start_motif_forge.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
    assert result.returncode == 0, result.stderr
    recorded = calls(log)
    sources = [row for row in recorded if row[0] == "deepseek-source"]
    assert sources and all(row[1] is False for row in sources)
    assert all(row[2] is enabled for row in sources)
    assert not any("up" in row for row in recorded)
    assert "sk-mock" not in result.stdout + result.stderr + log.read_text()


def test_beta_deepseek_is_explicit_and_never_logged(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    for relative in ("scripts/configure_deepseek.py", "compose.deepseek.yaml"):
        shutil.copy2(ROOT / relative, repo / relative)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    key_file = tmp_path / "config/motif-forge/deepseek.env"
    key_file.parent.mkdir(parents=True, mode=0o700)
    key_file.write_text("DEEPSEEK_API_KEY=sk-mock-0123456789abcdef\n")
    key_file.chmod(0o600)
    result = launch(repo, env, "--enable-deepseek", "--check")
    assert result.returncode == 0, result.stderr
    command = next(c for c in calls(log) if "config" in c)
    assert command.count("-f") == 3
    assert command.index(str(repo / "compose.deepseek.yaml")) > command.index(
        str(repo / "compose.personal-beta.yaml")
    )
    assert str(key_file) in command
    assert "sk-mock" not in result.stdout + result.stderr + log.read_text()
    assert not any("up" in c for c in calls(log))


def test_deepseek_missing_or_unsafe_secret_fails_before_docker(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    shutil.copy2(ROOT / "scripts/configure_deepseek.py", repo / "scripts/configure_deepseek.py")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    result = launch(repo, env, "--enable-deepseek", "--check")
    assert result.returncode == 78
    assert not calls(log)
    key_file = tmp_path / "config/motif-forge/deepseek.env"
    key_file.parent.mkdir(parents=True, mode=0o700)
    key_file.write_text("DEEPSEEK_API_KEY=sk-mock-0123456789abcdef\n")
    key_file.chmod(0o644)
    result = launch(repo, env, "--enable-deepseek", "--check")
    assert result.returncode == 78 and not calls(log)


def test_normal_launcher_can_explicitly_enable_key_without_beta(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    for relative in ("scripts/configure_deepseek.py", "compose.deepseek.yaml"):
        shutil.copy2(ROOT / relative, repo / relative)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    key_file = tmp_path / "config/motif-forge/deepseek.env"
    key_file.parent.mkdir(parents=True, mode=0o700)
    key_file.write_text("DEEPSEEK_API_KEY=sk-mock-0123456789abcdef\n")
    key_file.chmod(0o600)
    env["MOTIF_FORGE_DEV_STORAGE_ROOT"] = env["MOTIF_FORGE_BETA_STORAGE_ROOT"]
    result = subprocess.run(
        ["bash", str(repo / "scripts/start_motif_forge.sh"), "--enable-deepseek", "--check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    command = next(c for c in calls(log) if "config" in c)
    assert command.count("-f") == 2
    assert str(repo / "compose.personal-beta.yaml") not in command
    assert str(key_file) in command and str(repo / ".env") in command


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


@pytest.mark.parametrize("worker_tag", ["local", "acceptance-1"])
def test_real_compose_parser_proves_config_isolation_and_readonly_pin(
    tmp_path: Path, worker_tag: str
):
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
        "MOTIF_FORGE_BETA_IMAGE_TAG": worker_tag,
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
        expected = (
            "motif-forge-beta-api:inspector-a3bfb1a"
            if name in {"api", "migrate"}
            else f"motif-forge-beta-{image}:{worker_tag}"
        )
        assert services[name]["image"] == expected
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
    rollback = repo / "rollback-api.json"
    rollback_image = "sha256:" + "8" * 64
    rollback.write_text(json.dumps({"services": {"api": {"image": rollback_image}}}))
    launch_env = env | {"MOTIF_FORGE_BETA_RELEASE_IMAGE_ID": RELEASE["api_image"]["id"]}
    pinned = subprocess.run(result.args, env=launch_env, capture_output=True, text=True, timeout=20)
    assert pinned.returncode == 0, pinned.stderr
    pinned_services = json.loads(pinned.stdout)["services"]
    for name in ("api", "migrate"):
        assert pinned_services[name]["image"] == RELEASE["api_image"]["id"]
    restored = subprocess.run(
        [*result.args[:-3], "-f", str(rollback), "config", "--format", "json"],
        env=launch_env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert restored.returncode == 0, restored.stderr
    after = json.loads(restored.stdout)["services"]
    assert after["api"]["image"] == rollback_image
    assert {k: v for k, v in after["api"].items() if k != "image"} == {
        k: v for k, v in pinned_services["api"].items() if k != "image"
    }
    assert all(after[name] == service for name, service in pinned_services.items() if name != "api")


def test_checked_api_selection_is_independent_of_legacy_worker_tag(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    env["MOTIF_FORGE_BETA_IMAGE_TAG"] = "custom-worker"
    env["MOTIF_FORGE_BETA_RELEASE_IMAGE_ID"] = "sha256:" + "0" * 64
    result = launch(repo, env, "--check")
    assert result.returncode == 0, result.stderr
    images = [
        command[-1] for command in calls(log) if command[:3] == ["docker", "image", "inspect"]
    ]
    assert images == [
        RELEASE["api_image"]["reference"],
        "motif-forge-beta-api:custom-worker",
        "motif-forge-beta-media-worker:custom-worker",
        "motif-forge-beta-render-worker:custom-worker",
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_image_id",
        "wrong_compose_image",
        "wrong_migrator_image",
        "missing_contract",
        "wrong_local_schema",
        "missing_shared_python",
    ],
)
def test_release_mismatch_fails_before_any_start_or_write(tmp_path: Path, fault: str):
    repo, env, log = checkout(tmp_path)
    if fault == "wrong_image_id":
        env["BETA_API_IMAGE_ID"] = "sha256:" + "0" * 64
    elif fault == "wrong_compose_image":
        env["BETA_CONFIG_API_IMAGE"] = "motif-forge-beta-api:local"
    elif fault == "wrong_migrator_image":
        env["BETA_CONFIG_MIGRATE_IMAGE"] = "motif-forge-beta-api:unreviewed-migrator"
    elif fault == "missing_contract":
        (repo / "scripts/personal-beta-release.v1.json").unlink()
    elif fault == "missing_shared_python":
        env["BETA_MISSING_REF"] = "motif-forge-beta-api:local"
    else:
        (repo / "infra/migrations/versions/head.py").write_text(
            'revision="20261024_0031"\ndown_revision=None\n'
        )
    result = launch(repo, env, "--no-open")
    assert result.returncode == 78, result.stderr
    assert not any(
        "up" in c or "init" in c or "prepare" in c or "pull" in c or "build" in c
        for c in calls(log)
    )
    assert not (tmp_path / "runtime-personal-beta").exists()


def test_normal_nonbeta_check_keeps_legacy_configuration(tmp_path: Path):
    repo, env, log = checkout(tmp_path)
    env["MOTIF_FORGE_DEV_STORAGE_ROOT"] = str(tmp_path / "storage")
    (repo / "scripts/personal-beta-release.v1.json").unlink()
    result = subprocess.run(
        ["bash", str(repo / "scripts/start_motif_forge.sh"), "--check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not any(command[:3] == ["docker", "image", "inspect"] for command in calls(log))


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
