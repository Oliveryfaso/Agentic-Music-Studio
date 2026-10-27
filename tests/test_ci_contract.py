"""Keep public CI credential-free, bounded, and useful as a regression gate."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def _workflow():
    path = ROOT / ".github/workflows/ci.yml"
    assert path.is_file(), "Public regression workflow is missing"
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def test_ci_runs_main_and_pull_requests_without_privileged_event():
    workflow = _workflow()
    assert set(workflow["on"]) == {"push", "pull_request"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "true"


def test_ci_uses_standard_bounded_runners_without_runtime_services():
    workflow = _workflow()
    assert len(workflow["jobs"]) == 2
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"
        assert 1 <= int(job["timeout-minutes"]) <= 15
        assert "services" not in job
        assert "container" not in job


def test_ci_only_uses_pinned_official_actions_and_no_persistent_checkout_token():
    workflow = _workflow()
    actions = []
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" not in step:
                continue
            action, pin = step["uses"].split("@")
            assert action in {"actions/checkout", "actions/setup-python", "actions/setup-node"}
            assert re.fullmatch(r"[0-9a-f]{40}", pin)
            actions.append(action)
            if action == "actions/checkout":
                assert step["with"]["persist-credentials"] == "false"
    assert set(actions) == {"actions/checkout", "actions/setup-python", "actions/setup-node"}


def test_ci_disables_model_tracing_and_real_integration_optins():
    workflow = _workflow()
    env = workflow["env"]
    for key in (
        "DEEPSEEK_API_KEY",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "MOTIF_FORGE_TEST_POSTGRES_DSN",
        "MOTIF_FORGE_TEST_RENDER_IMAGE",
        "MOTIF_FORGE_TEST_REDIS_URL",
        "MOTIF_FORGE_TEST_ARTIFACT_ROOT",
    ):
        assert env[key] == ""
    assert env["LANGSMITH_TRACING"] == env["LANGCHAIN_TRACING_V2"] == "false"
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "secrets." not in text
    assert "pull_request_target" not in text


def test_ci_installs_locked_dependencies_and_runs_real_regression_commands():
    workflow = _workflow()
    commands = "\n".join(
        step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]
    )
    for expected in (
        "uv sync --frozen",
        "uv run pytest",
        "npm ci",
        "npm run test:web",
        "npm run test:audio",
        "npm run build:web",
        "npm run build:audio",
    ):
        assert expected in commands
    for unsafe in ("npm install", "docker compose up", "docker run", "alembic upgrade"):
        assert unsafe not in commands
