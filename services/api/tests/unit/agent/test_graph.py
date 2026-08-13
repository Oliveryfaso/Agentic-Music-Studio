import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from motif_forge.agent.graph import build_composition_plan_graph, initial_plan_state
from motif_forge.agent.planner import PlannerError, PlannerUsage, StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionPlan
from motif_forge.observability.models import ModelCallRecord

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
async def test_graph_routes_retryable_provider_failure_to_explicit_fallback() -> None:
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

    interrupted = await graph.ainvoke(
        initial_plan_state(
            run_id="run-failure",
            thread_id="thread-failure",
            brief_payload=valid_brief_payload(),
        ),
        {"configurable": {"thread_id": "thread-failure"}},
    )

    assert interrupted["phase"] == "plan_validated"
    assert interrupted["provider_metadata"]["provider"] == "deterministic"
    assert interrupted["error_policy"]["rule_id"] == "ERR-003"
    assert interrupted["warnings"]
    assert interrupted["__interrupt__"][0].value["warnings"]


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


@pytest.mark.asyncio
async def test_graph_repairs_invalid_plan_once_before_approval() -> None:
    repaired = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    graph = build_composition_plan_graph(
        StaticCompositionPlanner(
            {"schema_version": "composition-plan.v1"},
            repaired_plan=repaired,
        ),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "thread-repair"}}

    interrupted = await graph.ainvoke(
        initial_plan_state(
            run_id="run-repair",
            thread_id="thread-repair",
            brief_payload=valid_brief_payload(),
        ),
        config,
    )

    assert interrupted["phase"] == "plan_validated"
    assert interrupted["repair_attempts"] == 1
    assert interrupted["counters"]["model_calls"] == 2
    assert "__interrupt__" in interrupted


@pytest.mark.asyncio
async def test_standalone_graph_keeps_legacy_terminal_after_invalid_repair() -> None:
    invalid = {"schema_version": "composition-plan.v1"}
    graph = build_composition_plan_graph(
        StaticCompositionPlanner(invalid, repaired_plan=invalid),
        checkpointer=InMemorySaver(),
    )

    completed = await graph.ainvoke(
        initial_plan_state(
            run_id="run-invalid-repair",
            thread_id="thread-invalid-repair",
            brief_payload=valid_brief_payload(),
        ),
        {"configurable": {"thread_id": "thread-invalid-repair"}},
    )

    assert completed["terminal_status"] == "failed"
    assert completed["error"]["code"] == "PLAN_SCHEMA_INVALID"
    assert completed["counters"] == {"model_calls": 2, "total_tokens": 0}
    assert "__interrupt__" not in completed


@pytest.mark.asyncio
async def test_graph_does_not_repair_after_model_call_budget_is_exhausted() -> None:
    graph = build_composition_plan_graph(
        StaticCompositionPlanner({"schema_version": "composition-plan.v1"}),
        checkpointer=InMemorySaver(),
    )

    config = {"configurable": {"thread_id": "thread-budget"}}
    interrupted = await graph.ainvoke(
        initial_plan_state(
            run_id="run-budget",
            thread_id="thread-budget",
            brief_payload=valid_brief_payload(),
            max_model_calls=1,
        ),
        config,
    )

    assert interrupted["error"]["code"] == "SCHEMA_REPAIR_BUDGET_EXHAUSTED"
    assert interrupted["error"]["attempt"] == 1
    assert interrupted["__interrupt__"][0].value["options"] == ["fallback", "stop"]

    completed = await graph.ainvoke(Command(resume={"decision": "stop"}), config)
    assert completed["terminal_status"] == "failed"


@pytest.mark.asyncio
async def test_configuration_error_interrupts_before_human_chosen_fallback() -> None:
    planner = StaticCompositionPlanner(
        {},
        failure=PlannerError(
            "DEEPSEEK_HTTP_401",
            "DeepSeek configuration requires attention.",
            retryable=False,
            suggested_route="human",
        ),
    )
    graph = build_composition_plan_graph(planner, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread-auth"}}

    interrupted = await graph.ainvoke(
        initial_plan_state(
            run_id="run-auth",
            thread_id="thread-auth",
            brief_payload=valid_brief_payload(),
        ),
        config,
    )

    assert interrupted["__interrupt__"][0].value["options"] == ["fallback", "stop"]
    assert interrupted["error_policy"]["rule_id"] == "ERR-001"

    plan_interrupt = await graph.ainvoke(
        Command(resume={"decision": "fallback", "note": "Use a draft"}), config
    )
    assert plan_interrupt["phase"] == "plan_validated"
    assert plan_interrupt["provider_metadata"]["provider"] == "deterministic"


class RecordingTelemetry:
    def __init__(self) -> None:
        self.records: list[ModelCallRecord] = []

    async def record_model_call(self, record: ModelCallRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_graph_records_model_usage_without_reasoning() -> None:
    telemetry = RecordingTelemetry()
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    planner = StaticCompositionPlanner(plan)
    graph = build_composition_plan_graph(
        planner,
        checkpointer=InMemorySaver(),
        telemetry=telemetry,
    )

    await graph.ainvoke(
        initial_plan_state(
            run_id="run-trace",
            thread_id="thread-trace",
            brief_payload=valid_brief_payload(),
        ),
        {"configurable": {"thread_id": "thread-trace"}},
    )

    assert len(telemetry.records) == 1
    record = telemetry.records[0]
    assert record.response is not None
    assert record.response.usage == PlannerUsage()
    assert "reasoning_content" not in repr(record)
