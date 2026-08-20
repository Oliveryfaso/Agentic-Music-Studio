from __future__ import annotations

import json

import pytest
from motif_forge.agent.schemas import PlanAdjustment
from pydantic import ValidationError


def valid_adjustment_payload() -> dict[str, object]:
    return {
        "schema_version": "plan-adjustment.v1",
        "target_bpm": 92,
        "target_key": "D minor",
        "sections": [
            {"name": "Intro", "bars": 8, "energy": 0.2},
            {"name": "Lift", "bars": 16, "energy": 0.7},
        ],
        "instrumentation": [
            {"name": "Warm Pad", "role": "harmony"},
            {"name": "Soft Pulse", "role": "rhythm"},
        ],
        "note": "Keep the transition gradual.",
    }


def test_plan_adjustment_is_strict_bounded_and_requires_a_change() -> None:
    adjustment = PlanAdjustment.model_validate_json(
        json.dumps(valid_adjustment_payload()), strict=True
    )

    assert adjustment.target_bpm == 92
    assert sum(section.bars for section in adjustment.sections or ()) == 24
    for invalid in (
        {"schema_version": "plan-adjustment.v1", "note": ""},
        {**valid_adjustment_payload(), "target_bpm": "92"},
        {**valid_adjustment_payload(), "style": "techno"},
        {**valid_adjustment_payload(), "meter": "3/4"},
        {**valid_adjustment_payload(), "unknown": True},
        {
            **valid_adjustment_payload(),
            "sections": [
                {"name": "Too short", "bars": 2, "energy": 0.5},
                {"name": "Still short", "bars": 2, "energy": 0.5},
            ],
        },
    ):
        with pytest.raises(ValidationError):
            PlanAdjustment.model_validate_json(json.dumps(invalid), strict=True)
