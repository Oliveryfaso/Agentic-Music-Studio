"""Release update proposals only; local Git fixtures, no Docker, DB or Secret."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SOURCE = "14ce93714123edeb61a6e71a413882e68dd08385"
ENTRY = ROOT / "scripts/plan_personal_beta_api_update.py"


def module():
    assert ENTRY.is_file(), "API-only update planner is missing"
    spec = importlib.util.spec_from_file_location("api_update_plan", ENTRY)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / "source"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(ROOT), str(target)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "restore",
            "--source=" + SOURCE,
            "--staged",
            "--worktree",
            "--",
            "scripts/personal-beta-release.v1.json",
            "services/api/src",
            "infra/migrations",
            "services/render-worker",
            "packages/audio-engine",
            "pyproject.toml",
            "uv.lock",
            "services/api/Dockerfile",
            ".gitignore",
            ".dockerignore",
            "apps/web",
            "package.json",
            "package-lock.json",
            "tsconfig.json",
        ],
        cwd=target,
        check=True,
        capture_output=True,
    )
    return target


def test_web_only_commit_has_an_independent_identity_from_api_build(repo):
    path = repo / "apps/web/src/app/AppShell.tsx"
    path.write_text(path.read_text() + "\n// synthetic reviewed Web change\n")
    subprocess.run(["git", "add", "--", str(path)], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            "Synthetic Web identity",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    web = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    result = module().plan_update(repo, evidence(), web_commit=web)
    assert result["source_commit"] == SOURCE
    assert result["future_release_pin"]["application_commit"] == SOURCE
    assert result["web_source"]["new"] == web and web != SOURCE


def test_web_commit_cannot_hide_backend_drift_behind_restored_working_files(repo):
    path = repo / "services/api/src/motif_forge/api/app.py"
    path.write_text(path.read_text() + "\n# unreviewed committed backend change\n")
    subprocess.run(["git", "add", "--", str(path)], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            "Synthetic backend drift",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    web = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(
        ["git", "restore", "--source=" + SOURCE, "--staged", "--worktree", "--", str(path)],
        cwd=repo,
        check=True,
    )
    mod = module()
    with pytest.raises(mod.UpdatePlanError):
        mod.plan_update(repo, evidence(), web_commit=web)


@pytest.mark.parametrize("fault", ["changed", "ignored", "missing", "not_full_sha"])
def test_web_identity_or_source_drift_is_rejected(repo, fault):
    web = SOURCE
    if fault == "changed":
        path = repo / "apps/web/src/app/AppShell.tsx"
        path.write_text(path.read_text() + "\n// unreviewed Web drift\n")
    elif fault == "ignored":
        path = repo / "apps/web/build/probe.ts"
        path.parent.mkdir()
        path.write_text("// unreviewed ignored Web source\n")
        assert (
            subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=repo).returncode == 0
        )
    elif fault == "missing":
        web = "0" * 40
    else:
        web = "HEAD"
    mod = module()
    with pytest.raises(mod.UpdatePlanError):
        mod.plan_update(repo, evidence(), web_commit=web)


def evidence():
    return {
        "source_commit": SOURCE,
        "reference": "motif-forge-beta-api:settings-14ce937",
        "id": "sha256:" + "1" * 64,
        "files": {
            "motif_forge/api/app.py": (
                "e050fdec682537042ed9a883534b3ee5488584fb46334afc4e28e6a640c83a51"
            ),
            "motif_forge/api/model_settings.py": (
                "b84852cd80a949e9acbcf331080daa4a9aea32249e58af00761769b6e53b6ebe"
            ),
        },
    }


def test_proposal_is_api_only_and_rollback_uses_approved_old_id(repo):
    before = (repo / "scripts/personal-beta-release.v1.json").read_bytes()
    result = module().plan_update(repo, evidence(), web_commit=SOURCE)
    assert result["status"] == "NOT_READY_OFFLINE_PROPOSAL"
    assert result["compatible_database_revision"] == "20261020_0030"
    assert result["api_override"] == {"services": {"api": {"image": evidence()["id"]}}}
    old_id = json.loads(before)["api_image"]["id"]
    assert result["rollback_override"] == {"services": {"api": {"image": old_id}}}
    assert result["compose_suffix"] == [
        "up",
        "-d",
        "--no-deps",
        "--no-build",
        "--pull",
        "never",
        "api",
    ]
    assert result["future_release_pin"]["application_commit"] == SOURCE
    assert result["future_release_pin"]["api_image"]["id"] == evidence()["id"]
    assert result["never_start"] == ["migrate", "storage-init"]
    assert "resume-dispatcher" in result["retain_services"]
    assert "complete_activity_check" in result["pending_live_gates"]
    assert (repo / "scripts/personal-beta-release.v1.json").read_bytes() == before


@pytest.mark.parametrize("fault", ["id", "old_id", "reference", "source", "files", "extra"])
def test_wrong_or_stale_image_evidence_fails_closed(repo, fault):
    proposal = evidence()
    if fault == "old_id":
        proposal["id"] = json.loads((repo / "scripts/personal-beta-release.v1.json").read_text())[
            "api_image"
        ]["id"]
    elif fault == "source":
        proposal["source_commit"] = "0" * 40
    elif fault == "files":
        proposal["files"]["motif_forge/api/app.py"] = "0" * 64
    elif fault == "extra":
        proposal["secret"] = "synthetic-must-never-be-returned"
    else:
        proposal[fault] = "invalid"
    mod = module()
    with pytest.raises(mod.UpdatePlanError, match="BETA_UPDATE"):
        mod.plan_update(repo, proposal, web_commit=SOURCE)


@pytest.mark.parametrize(
    "fault", ["worker", "untracked_migration", "schema0031", "dockerfile", "ignored_source"]
)
def test_changed_worker_or_schema_stops_api_only_assumption(repo, fault):
    if fault == "worker":
        path = repo / "services/api/src/motif_forge/worker/celery_app.py"
        path.write_text(path.read_text() + "\n# synthetic worker drift\n")
    elif fault == "ignored_source":
        path = repo / "services/api/src/motif_forge/worker/build/probe.py"
        path.parent.mkdir()
        path.write_text("# synthetic ignored source drift\n")
        assert (
            subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=repo).returncode == 0
        )
    elif fault == "dockerfile":
        path = repo / "services/api/Dockerfile"
        path.write_text(path.read_text() + "\n# synthetic build drift\n")
    elif fault == "untracked_migration":
        (repo / "infra/migrations/versions/unreviewed.py").write_text(
            "revision='0031'\ndown_revision='20261020_0030'\n"
        )
    else:
        path = repo / "scripts/personal-beta-release.v1.json"
        value = json.loads(path.read_text())
        value["compatible_database_revision"] = "0031"
        path.write_text(json.dumps(value))
    mod = module()
    with pytest.raises(mod.UpdatePlanError):
        mod.plan_update(repo, evidence(), web_commit=SOURCE)


def test_cli_only_prints_proposal_and_sanitizes_bad_evidence(repo, tmp_path):
    proof = tmp_path / "evidence.json"
    proof.write_text(json.dumps(evidence()))
    before = (repo / "scripts/personal-beta-release.v1.json").read_bytes()
    result = subprocess.run(
        [
            "python3",
            str(ENTRY),
            "--repo",
            str(repo),
            "--image-evidence",
            str(proof),
            "--web-source",
            SOURCE,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "NOT_READY_OFFLINE_PROPOSAL"
    proof.write_text('{"secret":"synthetic-must-not-leak"}')
    result = subprocess.run(
        [
            "python3",
            str(ENTRY),
            "--repo",
            str(repo),
            "--image-evidence",
            str(proof),
            "--web-source",
            SOURCE,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 78 and result.stdout == ""
    assert "synthetic-must-not-leak" not in result.stderr and str(repo) not in result.stderr
    assert (repo / "scripts/personal-beta-release.v1.json").read_bytes() == before
