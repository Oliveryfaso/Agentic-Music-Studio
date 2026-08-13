import json

import pytest
from motif_forge.agent.planner import PlannerError, StaticCompositionPlanner
from motif_forge.agent.planning_subgraph import (
    build_composition_planning_subgraph,
    initial_planning_state,
)
from motif_forge.agent.schemas import CompositionPlan

from .sample_data import valid_brief_payload, valid_plan_payload


def _planner() -> StaticCompositionPlanner:
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    return StaticCompositionPlanner(plan)


def test_planning_subgraph_topology_excludes_human_and_side_effect_nodes() -> None:
    graph = build_composition_planning_subgraph(_planner())

    nodes = set(graph.get_graph().nodes)

    assert "PlanApproval" not in nodes
    assert "ErrorHuman" not in nodes
    assert "FinalizePlan" not in nodes
    assert "RejectPlan" not in nodes
    assert "PersistPlan" not in nodes
    assert "CreateRevision" not in nodes
    assert "EnqueueRender" not in nodes


@pytest.mark.asyncio
async def test_planning_subgraph_returns_validated_plan_without_interrupt() -> None:
    graph = build_composition_planning_subgraph(_planner())

    result = await graph.ainvoke(
        initial_planning_state(
            run_id="planning-success",
            thread_id="planning-success",
            brief_payload=valid_brief_payload(),
        )
    )

    assert result["phase"] == "planning_complete"
    assert result["plan"]["schema_version"] == "composition-plan.v1"
    assert result["counters"] == {"model_calls": 1, "total_tokens": 0}
    assert "__interrupt__" not in result
    assert "approval" not in result
    assert "human_error_decision" not in result


@pytest.mark.asyncio
async def test_planning_subgraph_fails_invalid_brief_without_human_interrupt() -> None:
    invalid_brief = {**valid_brief_payload(), "purpose": ""}
    graph = build_composition_planning_subgraph(_planner())

    result = await graph.ainvoke(
        initial_planning_state(
            run_id="planning-invalid-brief",
            thread_id="planning-invalid-brief",
            brief_payload=invalid_brief,
        )
    )

    assert result["phase"] == "planning_failed"
    assert result["error"]["code"] == "BRIEF_SCHEMA_INVALID"
    assert result["counters"] == {"model_calls": 0, "total_tokens": 0}
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_planning_subgraph_repairs_invalid_plan_once() -> None:
    repaired = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    graph = build_composition_planning_subgraph(
        StaticCompositionPlanner(
            {"schema_version": "composition-plan.v1"},
            repaired_plan=repaired,
        )
    )

    result = await graph.ainvoke(
        initial_planning_state(
            run_id="planning-repair",
            thread_id="planning-repair",
            brief_payload=valid_brief_payload(),
        )
    )

    assert result["phase"] == "planning_complete"
    assert result["counters"] == {"model_calls": 2, "total_tokens": 0}
    assert result["plan"]["schema_version"] == "composition-plan.v1"
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_planning_subgraph_uses_deterministic_fallback_after_provider_failure() -> None:
    graph = build_composition_planning_subgraph(
        StaticCompositionPlanner(
            {},
            failure=PlannerError(
                "DEEPSEEK_TIMEOUT",
                "DeepSeek did not respond within the configured timeout.",
                retryable=True,
                suggested_route="retry",
            ),
        )
    )

    result = await graph.ainvoke(
        initial_planning_state(
            run_id="planning-fallback",
            thread_id="planning-fallback",
            brief_payload=valid_brief_payload(),
        )
    )

    assert result["phase"] == "planning_complete"
    assert result["provider_metadata"]["provider"] == "deterministic"
    assert result["fallback_reason"] == "PROVIDER_RETRIES_EXHAUSTED"
    assert result["warnings"]
    assert result["plan"]["schema_version"] == "composition-plan.v1"
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_planning_subgraph_uses_fallback_when_repair_budget_is_exhausted() -> None:
    graph = build_composition_planning_subgraph(
        StaticCompositionPlanner({"schema_version": "composition-plan.v1"})
    )

    result = await graph.ainvoke(
        initial_planning_state(
            run_id="planning-budget",
            thread_id="planning-budget",
            brief_payload=valid_brief_payload(),
            max_model_calls=1,
        )
    )

    assert result["phase"] == "planning_complete"
    assert result["provider_metadata"]["provider"] == "deterministic"
    assert result["fallback_reason"] == "PROVIDER_REQUESTED_HUMAN"
    assert result["counters"] == {"model_calls": 1, "total_tokens": 0}
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_planning_subgraph_does_not_expose_provider_reasoning() -> None:
    graph = build_composition_planning_subgraph(_planner())

    result = await graph.ainvoke(
        initial_planning_state(
            run_id="planning-secret-safe",
            thread_id="planning-secret-safe",
            brief_payload=valid_brief_payload(),
        )
    )

    serialized = json.dumps(result, sort_keys=True)
    assert "reasoning_content" not in serialized
    assert "messages" not in result
    assert "raw_response" not in result
