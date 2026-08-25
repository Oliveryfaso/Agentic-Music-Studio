from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[4]))

from scripts.run_s7_eval_report import build_report

EVAL_PATH = Path(__file__).parents[4] / "evals" / "s7-portfolio-release-v1.json"


def test_s7_has_twenty_four_balanced_portfolio_cases() -> None:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 24
    assert len({item["id"] for item in cases}) == 24
    assert Counter(item["category"] for item in cases) == {
        "export": 8, "inspection": 6, "recovery": 6, "portfolio": 4,
    }


def test_s7_report_reaches_truthful_internal_and_public_inventory() -> None:
    report = build_report()
    assert report["internal_case_count"] >= 96
    assert report["public_measured_case_count"] >= 50
    assert report["s7_case_count"] == 24
    measured = report["summary"]["measured"]
    assert measured["denominator"] == measured["passed"] + measured["failed"]
    assert measured["denominator"] < report["internal_case_count"]
    assert report["current_run_usage"] == {"provider_requests": 0, "total_tokens": 0}
