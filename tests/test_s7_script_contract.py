from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SMOKE = ROOT / "scripts/run_s7_portfolio_smoke.py"
BROWSER = ROOT / "scripts/run_s7_browser_smoke.mjs"
GATE = ROOT / "scripts/check_s7.sh"


def test_s7_smoke_uses_public_reads_and_attests_no_paid_usage() -> None:
    source = SMOKE.read_text(encoding="utf-8")
    assert "execute_media_job" not in source
    assert "_assert_no_paid_runtime" in source
    assert '"submitted_model_requests": 0' in source
    assert '"total_tokens": 0' in source
    assert "/inspect" in source and "/exports" in source
    assert "/files/" in source and "/audio-artifacts/" in source


def test_s7_browser_smoke_covers_evidence_inspector_export_and_mobile() -> None:
    source = BROWSER.read_text(encoding="utf-8")
    for required in ("/about", "/evaluation", "/inspect", "/exports/", "width: 390"):
        assert required in source
    subprocess.run(["node", "--check", str(BROWSER)], check=True)


def test_s7_gate_and_package_commands_are_executable() -> None:
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["smoke:s7"] == (
        "PYTHONPATH=services/api/src .venv/bin/python -m scripts.run_s7_portfolio_smoke"
    )
    assert scripts["smoke:s7:browser"] == "node scripts/run_s7_browser_smoke.mjs"
    source = GATE.read_text(encoding="utf-8")
    for required in (
        "test_s7_portfolio_eval.py", "test:web", "build:web", "generate:openapi",
        "ruff", "mypy", "test_postgres_s7", "git diff --check",
    ):
        assert required in source
