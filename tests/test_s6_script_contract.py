from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_s6_smoke_contract_is_bounded_and_no_key() -> None:
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from scripts.run_s6_deterministic_smoke import run_contract_fixture

    assert run_contract_fixture() == {
        "manual_revisions": 2,
        "undo_revisions": 1,
        "l0_revisions": 1,
        "l2_previews": 1,
        "l2_approved_revisions": 1,
        "provider_requests": 0,
        "provider_tokens": 0,
    }


def test_s6_smokes_use_public_boundaries_and_never_execute_workers_directly() -> None:
    root = Path(__file__).parents[1]
    deterministic = (root / "scripts/run_s6_deterministic_smoke.py").read_text(
        encoding="utf-8"
    )
    browser = (root / "scripts/run_s6_browser_smoke.mjs").read_text(encoding="utf-8")
    forbidden = ("worker.execution", "execute_media_job", "CommitCommandBatch(")
    assert all(value not in deterministic for value in forbidden)
    assert "/api/v1/projects" in deterministic
    assert "app.ai_runs" in deterministic
    assert 'run_type=\'edit\'' in deterministic
    assert '"docker", "compose", "ps", "-q", "resume-dispatcher"' in deterministic
    assert "page.goto" in browser
    subprocess.run(
        ["node", "--check", str(root / "scripts/run_s6_browser_smoke.mjs")],
        check=True,
    )


def test_s6_stage_gate_and_package_commands_are_executable() -> None:
    root = Path(__file__).parents[1]
    scripts = json.loads((root / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["smoke:s6"] == ".venv/bin/python -m scripts.run_s6_deterministic_smoke"
    assert scripts["smoke:s6:browser"] == "node scripts/run_s6_browser_smoke.mjs"
    gate = root / "scripts/check_s6.sh"
    assert gate.exists()
    assert "test_s6_edit_eval.py" in gate.read_text(encoding="utf-8")


def test_s6_no_key_runtime_cannot_inherit_provider_secret() -> None:
    root = Path(__file__).parents[1]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    resume = compose.split("  resume-dispatcher:\n", 1)[1].split(
        "\n  media-worker:", 1
    )[0]
    assert 'DEEPSEEK_API_KEY: ""' in resume
