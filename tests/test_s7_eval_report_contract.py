from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.run_s7_eval_report import render_outputs


def test_s7_eval_report_is_deterministic_bounded_and_secret_safe(tmp_path: Path) -> None:
    first_json, first_markdown = render_outputs()
    second_json, second_markdown = render_outputs()
    assert first_json == second_json
    assert first_markdown == second_markdown
    assert len(first_json) < 64_000
    assert len(first_markdown) < 32_000
    serialized = first_json.decode() + first_markdown
    for forbidden in (
        "generated_at", "DEEPSEEK_API_KEY", "approval_assertion", "/Volumes/", "storage_key",
    ):
        assert forbidden not in serialized
    assert '"classification":"not_measured"' in first_json.decode()
