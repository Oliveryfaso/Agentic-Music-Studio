from __future__ import annotations

import json
from pathlib import Path

from motif_forge.agent.schemas import CompositionBrief, PlanAdjustment
from motif_forge.application.ai_runs import derive_replan_brief
from pydantic import ValidationError

EVAL_PATH = Path(__file__).parents[4] / "evals" / "s3-plan-replan-v1.json"


def test_s3_replan_eval_has_one_valid_and_one_stable_invalid_result() -> None:
    cases = json.loads(EVAL_PATH.read_text())
    assert isinstance(cases, list)
    assert len(cases) == 2
    parent = CompositionBrief.model_validate_json(json.dumps({
        "schema_version": "composition-brief.v1",
        "title": "Orbital Glass",
        "purpose": "Instrumental background for a puzzle",
        "style": "synth_ambient",
        "duration_seconds": 96,
        "target_bpm": 80,
        "target_key": "A minor",
        "meter": "4/4",
        "moods": ["calm", "curious"],
        "preferred_instruments": ["Warm Pad"],
        "hard_constraints": [],
        "soft_preferences": ["slow evolution"],
        "negative_constraints": ["no abrupt drop"],
    }), strict=True)
    results: dict[str, str] = {}

    for case in cases:
        try:
            adjustment = PlanAdjustment.model_validate_json(
                json.dumps(case["adjustment"]), strict=True
            )
        except ValidationError:
            results[case["id"]] = "PLAN_ADJUSTMENT_INVALID"
            continue
        child = derive_replan_brief(parent, adjustment)
        assert child.target_bpm == adjustment.target_bpm
        assert child.target_key == adjustment.target_key
        assert child.preferred_instruments == tuple(
            item.name for item in adjustment.instrumentation or ()
        )
        assert child != parent
        results[case["id"]] = "CHILD_BRIEF_DERIVED"

    assert results == {case["id"]: case["expected_label"] for case in cases}
