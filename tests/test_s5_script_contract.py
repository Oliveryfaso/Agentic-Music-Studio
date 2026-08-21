from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_s5_smoke_controlled_contract_has_exact_bounded_facts() -> None:
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from scripts.run_s5_deterministic_smoke import run_contract_fixture

    result = run_contract_fixture()
    assert result == {
        "provider_requests": 0,
        "provider_tokens": 0,
        "candidate_snapshots": 3,
        "selection_previews": 2,
        "selected_revisions": 1,
        "export_jobs": 7,
        "audio_artifacts": 6,
        "bundles": 1,
    }


def test_s5_stage_gate_exposes_executable_runtime_and_browser_smokes() -> None:
    root = Path(__file__).parents[1]
    scripts = json.loads((root / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["smoke:s5"] == ".venv/bin/python -m scripts.run_s5_deterministic_smoke"
    assert scripts["smoke:s5:browser"] == "node scripts/run_s5_browser_smoke.mjs"
    subprocess.run(
        ["node", "--check", str(root / "scripts" / "run_s5_browser_smoke.mjs")],
        check=True,
    )
