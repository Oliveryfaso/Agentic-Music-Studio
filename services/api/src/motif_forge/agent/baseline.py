"""Minimal hand-written planning loop used as a framework comparison baseline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from motif_forge.agent.planner import CompositionPlanner, PlannerUsage
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan


@dataclass(frozen=True, slots=True)
class BaselineResult:
    status: str
    plan: CompositionPlan | None
    attempts: int
    usage: PlannerUsage
    error_code: str | None = None


async def run_planning_baseline(
    brief_payload: dict[str, Any],
    planner: CompositionPlanner,
    *,
    max_steps: int = 2,
) -> BaselineResult:
    """Run validate -> decide -> validate -> stop with a hard step limit.

    This intentionally omits persistence and HITL. It is retained for protocol/eval
    comparisons with LangGraph, not used as a second production orchestrator.
    """

    if not 1 <= max_steps <= 3:
        raise ValueError("max_steps must be between 1 and 3")
    try:
        brief = CompositionBrief.model_validate_json(json.dumps(brief_payload), strict=True)
    except ValidationError:
        return BaselineResult(
            status="failed",
            plan=None,
            attempts=0,
            usage=PlannerUsage(),
            error_code="BRIEF_SCHEMA_INVALID",
        )

    last_usage = PlannerUsage()
    for attempt in range(1, max_steps + 1):
        response = await planner.create_plan(brief)
        last_usage = response.usage
        try:
            plan = CompositionPlan.model_validate_json(
                json.dumps(response.plan_payload), strict=True
            )
        except ValidationError:
            if attempt == max_steps:
                return BaselineResult(
                    status="failed",
                    plan=None,
                    attempts=attempt,
                    usage=last_usage,
                    error_code="PLAN_SCHEMA_INVALID",
                )
            continue
        return BaselineResult(
            status="ready_for_approval",
            plan=plan,
            attempts=attempt,
            usage=last_usage,
        )

    raise AssertionError("bounded baseline loop exited unexpectedly")
