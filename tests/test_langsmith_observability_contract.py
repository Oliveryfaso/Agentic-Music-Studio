from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _resolved_compose() -> dict[str, object]:
    environment = {
        **os.environ,
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "lsv2_pt_compose-boundary-test",
        "LANGSMITH_PROJECT": "motif-forge-contract",
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def test_compose_limits_langsmith_secret_to_observed_python_services() -> None:
    compose = _resolved_compose()
    services = compose["services"]
    assert isinstance(services, dict)

    for service_name in ("api", "dispatcher", "resume-dispatcher"):
        environment = services[service_name]["environment"]
        assert environment["LANGSMITH_TRACING"] == "true"
        assert environment["LANGSMITH_API_KEY"] == "lsv2_pt_compose-boundary-test"
        assert environment["LANGSMITH_PROJECT"] == "motif-forge-contract"
        assert environment["LANGSMITH_HIDE_INPUTS"] == "true"
        assert environment["LANGSMITH_HIDE_OUTPUTS"] == "true"
        assert environment["LANGCHAIN_CALLBACKS_BACKGROUND"] == "true"

    for service_name in ("migrate", "media-worker"):
        environment = services[service_name]["environment"]
        assert environment["LANGSMITH_TRACING"] == "false"
        assert environment["LANGSMITH_API_KEY"] == ""

    for service_name in ("render-worker", "storage-init", "postgres", "redis"):
        environment = services[service_name].get("environment", {})
        assert environment.get("LANGSMITH_API_KEY", "") == ""
        assert environment.get("LANGSMITH_TRACING", "false") == "false"


def test_langsmith_environment_defaults_off() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "LANGSMITH_TRACING=false" in example
    assert "LANGSMITH_API_KEY=" in example
    assert "LANGSMITH_HIDE_INPUTS=true" in example
    assert "LANGSMITH_HIDE_OUTPUTS=true" in example


def test_readme_documents_opt_in_disable_privacy_and_cost_controls() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for required in (
        "## Optional LangSmith tracing",
        "LANGSMITH_TRACING=true",
        "LANGSMITH_API_KEY=",
        "LANGSMITH_TRACING=false",
        "scripts/build_compose_images.sh api",
        "scripts/start_motif_forge.sh",
        "scripts/stop_motif_forge.sh",
        "inputs and outputs are hidden",
        "PostgreSQL remains authoritative",
        "retention",
        "spend limit",
    ):
        assert required in readme
