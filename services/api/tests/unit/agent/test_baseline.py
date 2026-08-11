import json

import pytest
from motif_forge.agent.baseline import run_planning_baseline
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionPlan

from .sample_data import valid_brief_payload, valid_plan_payload


@pytest.mark.asyncio
async def test_handwritten_baseline_stops_after_valid_plan() -> None:
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)

    result = await run_planning_baseline(
        valid_brief_payload(), StaticCompositionPlanner(plan), max_steps=2
    )

    assert result.status == "ready_for_approval"
    assert result.attempts == 1
    assert result.plan == plan


@pytest.mark.asyncio
async def test_handwritten_baseline_has_hard_invalid_plan_limit() -> None:
    result = await run_planning_baseline(
        valid_brief_payload(), StaticCompositionPlanner({"schema_version": "wrong"}), max_steps=2
    )

    assert result.status == "failed"
    assert result.attempts == 2
    assert result.error_code == "PLAN_SCHEMA_INVALID"
