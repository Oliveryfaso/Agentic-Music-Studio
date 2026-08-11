import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from motif_forge.agent.graph import build_composition_plan_graph, initial_plan_state
from motif_forge.agent.planner import PlannerError, StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionPlan

from .sample_data import valid_brief_payload, valid_plan_payload


def _planner() -> StaticCompositionPlanner:
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    return StaticCompositionPlanner(plan)


@pytest.mark.asyncio
async def test_graph_interrupts_and_resumes_approval() -> None:
    graph = build_composition_plan_graph(_planner(), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread-approve"}}

    interrupted = await graph.ainvoke(
        initial_plan_state(
            run_id="run-approve",
            thread_id="thread-approve",
            brief_payload=valid_brief_payload(),
        ),
        config,
    )

    assert interrupted["phase"] == "plan_validated"
    assert interrupted["__interrupt__"][0].value["options"] == ["approve", "reject"]
    assert "plan_summary" in interrupted["__interrupt__"][0].value

    completed = await graph.ainvoke(
        Command(resume={"decision": "approve", "note": "Looks good"}), config
    )

    assert completed["terminal_status"] == "approved"
    assert completed["approval"]["decision"] == "approve"
    assert completed["phase"] == "complete"


@pytest.mark.asyncio
async def test_graph_reject_route_is_terminal() -> None:
    graph = build_composition_plan_graph(_planner(), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread-reject"}}
    await graph.ainvoke(
        initial_plan_state(
            run_id="run-reject",
            thread_id="thread-reject",
            brief_payload=valid_brief_payload(),
        ),
        config,
    )

    completed = await graph.ainvoke(
        Command(resume={"decision": "reject", "note": "Try a darker form"}), config
    )

    assert completed["terminal_status"] == "rejected"


@pytest.mark.asyncio
async def test_graph_routes_planner_failure_to_structured_error() -> None:
    planner = StaticCompositionPlanner(
        {},
        failure=PlannerError(
            "DEEPSEEK_TIMEOUT",
            "DeepSeek did not respond within the configured timeout.",
            retryable=True,
            suggested_route="retry",
        ),
    )
    graph = build_composition_plan_graph(planner, checkpointer=InMemorySaver())

    completed = await graph.ainvoke(
        initial_plan_state(
            run_id="run-failure",
            thread_id="thread-failure",
            brief_payload=valid_brief_payload(),
        ),
        {"configurable": {"thread_id": "thread-failure"}},
    )

    assert completed["terminal_status"] == "failed"
    assert completed["error"]["code"] == "DEEPSEEK_TIMEOUT"
    assert completed["error"]["retryable"] is True
    assert completed["error"]["suggested_route"] == "retry"


@pytest.mark.asyncio
async def test_graph_routes_invalid_plan_without_interrupting() -> None:
    graph = build_composition_plan_graph(
        StaticCompositionPlanner({"schema_version": "composition-plan.v1"}),
        checkpointer=InMemorySaver(),
    )

    completed = await graph.ainvoke(
        initial_plan_state(
            run_id="run-invalid-plan",
            thread_id="thread-invalid-plan",
            brief_payload=valid_brief_payload(),
        ),
        {"configurable": {"thread_id": "thread-invalid-plan"}},
    )

    assert completed["terminal_status"] == "failed"
    assert completed["error"]["code"] == "PLAN_SCHEMA_INVALID"
    assert "__interrupt__" not in completed
