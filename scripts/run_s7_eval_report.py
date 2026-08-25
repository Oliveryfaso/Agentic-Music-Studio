"""Build deterministic, denominator-safe S7 portfolio Eval artifacts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
S7_PATH = ROOT / "evals/s7-portfolio-release-v1.json"
JSON_TARGET = ROOT / "apps/web/public/evals/s7-report.v1.json"
MARKDOWN_TARGET = ROOT / "docs/evals/S7_EVAL_REPORT.md"

STAGE_INVENTORY = {
    "S1": {"internal": 20, "measured": 20, "expected_reject": 0, "not_measured": 0},
    "S2": {"internal": 16, "measured": 10, "expected_reject": 6, "not_measured": 0},
    "S3": {"internal": 2, "measured": 1, "expected_reject": 1, "not_measured": 0},
    "S4": {"internal": 10, "measured": 8, "expected_reject": 2, "not_measured": 0},
    "S5": {"internal": 12, "measured": 11, "expected_reject": 1, "not_measured": 0},
    "S6": {"internal": 12, "measured": 11, "expected_reject": 0, "not_measured": 1},
}


def _s7_cases() -> list[dict[str, str]]:
    payload = json.loads(S7_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    if payload["schema_version"] != "s7-portfolio-eval.v1" or not isinstance(cases, list):
        raise ValueError("S7_EVAL_SCHEMA_INVALID")
    return cases


def build_report() -> dict[str, Any]:
    cases = _s7_cases()
    classifications = Counter(case["expected"] for case in cases)
    s7_measured = classifications["measured_pass"] + classifications["measured_fail"]
    stage_inventory = {
        **STAGE_INVENTORY,
        "S7": {
            "internal": len(cases), "measured": s7_measured,
            "expected_reject": classifications["expected_reject"],
            "not_measured": classifications["not_measured"],
        },
    }
    measured_denominator = sum(item["measured"] for item in stage_inventory.values())
    measured_failures = classifications["measured_fail"]
    return {
        "schema_version": "motif-forge-eval-report.v1",
        "dataset_version": "s1-s7.portfolio.v1",
        "internal_case_count": sum(item["internal"] for item in stage_inventory.values()),
        "public_measured_case_count": measured_denominator,
        "s7_case_count": len(cases),
        "stage_inventory": stage_inventory,
        "summary": {
            "measured": {
                "denominator": measured_denominator,
                "passed": measured_denominator - measured_failures,
                "failed": measured_failures,
            },
            "expected_reject": sum(
                item["expected_reject"] for item in stage_inventory.values()
            ),
            "not_measured": sum(item["not_measured"] for item in stage_inventory.values()),
        },
        "s7_categories": dict(sorted(Counter(case["category"] for case in cases).items())),
        "s7_results": [
            {
                "id": case["id"], "category": case["category"],
                "behavior": case["behavior"], "classification": case["expected"],
                "measurement": case["measurement"],
            }
            for case in cases
        ],
        "latency": {
            "measurement": "bucketed_upper_bound",
            "scope": "focused deterministic evaluators",
            "p50_ms": "<100", "p95_ms": "<100",
        },
        "current_run_usage": {"provider_requests": 0, "total_tokens": 0},
        "historical_live_acceptance": {
            "stage": "S2", "bounded_provider_requests": 1,
            "evidence": "persistent one-request DeepSeek acceptance; not rerun by S7",
        },
        "not_measured_claims": [
            "perceptual audio quality", "clipping absence without audio analysis",
            "mobile visual quality until browser smoke",
        ],
    }


def render_outputs() -> tuple[bytes, str]:
    report = build_report()
    json_bytes = json.dumps(
        report, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8") + b"\n"
    measured = report["summary"]["measured"]
    markdown = "\n".join((
        "# Motif Forge S7 Eval Report",
        "",
        "This report separates measured behavior, expected rejection, and unmeasured claims.",
        "",
        f"- Internal inventory: **{report['internal_case_count']} cases**",
        f"- Public measured inventory: **{report['public_measured_case_count']} cases**",
        f"- Measured pass: **{measured['passed']}/{measured['denominator']}**",
        f"- Expected reject: **{report['summary']['expected_reject']}**",
        f"- Not measured: **{report['summary']['not_measured']}**",
        "- Current deterministic provider usage: **0 requests / 0 tokens**",
        "- Focused latency buckets: **P50 <100 ms / P95 <100 ms**",
        "",
        "## Stage inventory",
        "",
        *(
            f"- {stage}: {values['internal']} internal / {values['measured']} measured"
            for stage, values in report["stage_inventory"].items()
        ),
        "",
        "## Explicitly not measured",
        "",
        *(f"- {claim}" for claim in report["not_measured_claims"]),
        "",
        "Historical S2 live-provider acceptance is listed separately and is not "
        "rerun by this report.",
        "",
    ))
    return json_bytes, markdown


def main() -> None:
    json_bytes, markdown = render_outputs()
    JSON_TARGET.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_TARGET.parent.mkdir(parents=True, exist_ok=True)
    JSON_TARGET.write_bytes(json_bytes)
    MARKDOWN_TARGET.write_text(markdown, encoding="utf-8")
    print(json.dumps({
        "internal_case_count": build_report()["internal_case_count"],
        "public_measured_case_count": build_report()["public_measured_case_count"],
        "provider_requests": 0, "total_tokens": 0,
    }, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
