"""Reusable, side-effect-free CompositionPlan planning workflow."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, NotRequired, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.planner import CompositionPlanner, PlannerError
from motif_forge.agent.schemas import (
    AgentErrorEnvelope,
    CompositionBrief,
    CompositionPlan,
    PlanningResult,
)
from motif_forge.domain.error_policy import ErrorFacts, classify_agent_error
from motif_forge.observability.models import (
    ModelCallRecord,
    NullTelemetryRecorder,
    TelemetryRecorder,
)

PLANNING_GRAPH_TOPOLOGY_VERSION = "motif-forge-plan.v3"
PLANNING_STATE_SCHEMA_VERSION = "motif-forge-plan-state.v3"


class PlanningSubgraphState(TypedDict):
    run_id: str
    thread_id: str
    graph_topology_version: str
    state_schema_version: str
    brief_payload: Mapping[str, Any]
    phase: str
    brief: NotRequired[dict[str, Any]]
    plan_payload: NotRequired[dict[str, Any]]
    plan: NotRequired[dict[str, Any]]
    provider_metadata: NotRequired[dict[str, str]]
    usage: NotRequired[dict[str, int]]
    budget: dict[str, int]
    counters: dict[str, int]
    validation_issues: NotRequired[list[str]]
    repair_attempts: int
    approval: NotRequired[dict[str, str]]
    error: NotRequired[dict[str, Any] | None]
    error_route: NotRequired[str]
    error_policy: NotRequired[dict[str, str]]
    fallback_reason: NotRequired[str]
    warnings: NotRequired[list[str]]
    human_error_decision: NotRequired[dict[str, str]]
    terminal_status: NotRequired[Literal["approved", "rejected", "failed"]]


class PlanningNodes:
    """Shared planning nodes and routes used by both Graph topologies."""

    def __init__(
        self,
        planner: CompositionPlanner,
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        self.planner = planner
        self.recorder = telemetry or NullTelemetryRecorder()

    async def validate_brief(self, state: PlanningSubgraphState) -> dict[str, Any]:
        try:
            brief = CompositionBrief.model_validate_json(
                json.dumps(state["brief_payload"]), strict=True
            )
        except ValidationError:
            return error_update(
                state,
                node="ValidateBrief",
                category="input",
                code="BRIEF_SCHEMA_INVALID",
                summary="The composition brief does not match the required schema.",
                retryable=False,
                suggested_route="human",
            )
        return {"brief": brief.model_dump(mode="json"), "phase": "brief_validated"}

    async def run_planner(self, state: PlanningSubgraphState, *, repair: bool) -> dict[str, Any]:
        brief_payload = state.get("brief")
        node_name = "RepairPlan" if repair else "CompositionPlanner"
        if brief_payload is None:
            return error_update(
                state,
                node=node_name,
                category="internal",
                code="VALIDATED_BRIEF_MISSING",
                summary="The validated composition brief is unavailable.",
                retryable=False,
                suggested_route="terminal",
            )
        brief = CompositionBrief.model_validate_json(json.dumps(brief_payload), strict=True)
        counters = state["counters"]
        budget = state["budget"]
        if counters["model_calls"] >= budget["max_model_calls"]:
            return error_update(
                state,
                node=node_name,
                category="model_provider",
                code="MODEL_CALL_BUDGET_EXHAUSTED",
                summary="The model-call budget was exhausted before planning completed.",
                retryable=False,
                suggested_route="human",
            )

        started_at = datetime.now(UTC)
        try:
            if repair:
                response = await self.planner.repair_plan(
                    brief,
                    invalid_payload=state.get("plan_payload", {}),
                    validation_issues=tuple(state.get("validation_issues", ())),
                )
            else:
                response = await self.planner.create_plan(
                    brief,
                    allow_schema_repair=(budget["max_model_calls"] - counters["model_calls"] >= 2),
                )
        except PlannerError as exc:
            ended_at = datetime.now(UTC)
            try:
                await self.recorder.record_model_call(
                    ModelCallRecord(
                        operation_id=(
                            f"{state['run_id']}:{node_name}:"
                            f"{counters['model_calls'] + 1}:error:{exc.code}"
                        ),
                        run_id=state["run_id"],
                        thread_id=state["thread_id"],
                        node=node_name,
                        provider="deepseek",
                        model="deepseek-v4-flash",
                        prompt_version="composition-planner.v1",
                        schema_version="composition-plan.v1",
                        thinking_mode="enabled",
                        response=None,
                        status="failed",
                        error_code=exc.code,
                        started_at=started_at,
                        ended_at=ended_at,
                    )
                )
            except Exception:
                return error_update(
                    state,
                    node=node_name,
                    category="internal",
                    code="OBSERVABILITY_WRITE_FAILED",
                    summary="Model telemetry could not be persisted safely.",
                    retryable=False,
                    suggested_route="terminal",
                )
            return error_update(
                state,
                node=node_name,
                category="model_provider",
                code=exc.code,
                summary=exc.safe_summary,
                retryable=exc.retryable,
                suggested_route=cast(
                    Literal["retry", "repair", "fallback", "human", "terminal"],
                    exc.suggested_route,
                ),
                provider="deepseek",
                model="deepseek-v4-flash",
            )
        except Exception:
            return error_update(
                state,
                node=node_name,
                category="internal",
                code="PLANNER_UNEXPECTED_FAILURE",
                summary="The composition planner failed unexpectedly.",
                retryable=False,
                suggested_route="terminal",
            )

        ended_at = datetime.now(UTC)
        operation_id = response.operation_id or (
            f"{state['run_id']}:{node_name}:{counters['model_calls'] + 1}"
        )
        try:
            await self.recorder.record_model_call(
                ModelCallRecord(
                    operation_id=operation_id,
                    run_id=state["run_id"],
                    thread_id=state["thread_id"],
                    node=node_name,
                    provider=response.provider,
                    model=response.model,
                    prompt_version=response.prompt_version,
                    schema_version=response.schema_version,
                    thinking_mode="enabled",
                    response=response,
                    status="succeeded",
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )
        except Exception:
            return error_update(
                state,
                node=node_name,
                category="internal",
                code="OBSERVABILITY_WRITE_FAILED",
                summary="Model telemetry could not be persisted safely.",
                retryable=False,
                suggested_route="terminal",
            )

        usage = response.usage.as_dict()
        cumulative_usage = {
            key: state.get("usage", {}).get(key, 0) + value for key, value in usage.items()
        }
        next_counters = {
            "model_calls": counters["model_calls"] + response.model_calls,
            "total_tokens": counters["total_tokens"] + response.usage.total_tokens,
        }
        update: dict[str, Any] = {
            "plan_payload": dict(response.plan_payload),
            "provider_metadata": {
                "provider": response.provider,
                "model": response.model,
                "prompt_version": response.prompt_version,
                "schema_version": response.schema_version,
            },
            "usage": cumulative_usage,
            "counters": next_counters,
            "phase": "plan_repaired" if repair else "plan_proposed",
        }
        if repair:
            update["repair_attempts"] = state["repair_attempts"] + 1
        if (
            next_counters["model_calls"] > budget["max_model_calls"]
            or next_counters["total_tokens"] > budget["max_total_tokens"]
        ):
            update.update(
                error_update(
                    {**state, "counters": next_counters},
                    node=node_name,
                    category="model_provider",
                    code="MODEL_BUDGET_EXHAUSTED",
                    summary="The planning response exceeded the configured model budget.",
                    retryable=False,
                    suggested_route="human",
                    provider=response.provider,
                    model=response.model,
                )
            )
        return update

    async def composition_planner(self, state: PlanningSubgraphState) -> dict[str, Any]:
        return await self.run_planner(state, repair=False)

    async def repair_plan(self, state: PlanningSubgraphState) -> dict[str, Any]:
        return await self.run_planner(state, repair=True)

    async def validate_plan(self, state: PlanningSubgraphState) -> dict[str, Any]:
        payload = state.get("plan_payload")
        if payload is None:
            return error_update(
                state,
                node="ValidatePlan",
                category="internal",
                code="PLAN_PAYLOAD_MISSING",
                summary="The composition planner returned no plan payload.",
                retryable=False,
                suggested_route="terminal",
            )
        try:
            plan = CompositionPlan.model_validate_json(json.dumps(payload), strict=True)
        except ValidationError as exc:
            if state["repair_attempts"] < 1:
                if state["counters"]["model_calls"] >= state["budget"]["max_model_calls"]:
                    return error_update(
                        state,
                        node="ValidatePlan",
                        category="schema",
                        code="SCHEMA_REPAIR_BUDGET_EXHAUSTED",
                        summary=(
                            "The plan is invalid and no model-call budget remains for repair."
                        ),
                        retryable=False,
                        suggested_route="human",
                        provider=state.get("provider_metadata", {}).get("provider"),
                        model=state.get("provider_metadata", {}).get("model"),
                    )
                return {
                    "phase": "plan_repair_needed",
                    "validation_issues": safe_validation_issues(exc),
                }
            return error_update(
                state,
                node="ValidatePlan",
                category="schema",
                code="PLAN_SCHEMA_INVALID",
                summary="The proposed composition plan failed deterministic validation.",
                retryable=False,
                suggested_route="repair",
                provider=state.get("provider_metadata", {}).get("provider"),
                model=state.get("provider_metadata", {}).get("model"),
            )
        return {"plan": plan.model_dump(mode="json"), "phase": "plan_validated"}

    async def error_router(self, state: PlanningSubgraphState) -> dict[str, Any]:
        error = state.get("error")
        if error is None:
            return error_update(
                state,
                node="ErrorRouter",
                category="internal",
                code="ERROR_ENVELOPE_MISSING",
                summary="The error router received no error envelope.",
                retryable=False,
                suggested_route="terminal",
            )
        decision = classify_agent_error(
            ErrorFacts(
                category=str(error["category"]),
                code=str(error["code"]),
                retryable=bool(error["retryable"]),
                suggested_route=str(error["suggested_route"]),
                repair_attempts=state["repair_attempts"],
                model_calls_remaining=max(
                    0,
                    state["budget"]["max_model_calls"] - state["counters"]["model_calls"],
                ),
            )
        )
        return {
            "phase": "error_classified",
            "error_route": decision.route,
            "error_policy": {
                "policy_version": decision.policy_version,
                "rule_id": decision.rule_id,
                "explanation_code": decision.explanation_code,
            },
        }

    async def deterministic_fallback(self, state: PlanningSubgraphState) -> dict[str, Any]:
        brief_payload = state.get("brief")
        if brief_payload is None:
            return error_update(
                state,
                node="DeterministicPlanFallback",
                category="internal",
                code="FALLBACK_BRIEF_MISSING",
                summary="A deterministic fallback cannot run without a validated brief.",
                retryable=False,
                suggested_route="terminal",
            )
        brief = CompositionBrief.model_validate_json(json.dumps(brief_payload), strict=True)
        plan = build_fallback_plan(brief)
        fallback_reason = state.get("fallback_reason") or state.get("error_policy", {}).get(
            "explanation_code", "MODEL_OUTPUT_UNUSABLE"
        )
        return {
            "error": None,
            "plan_payload": plan.model_dump(mode="json"),
            "provider_metadata": {
                "provider": "deterministic",
                "model": "composition-template",
                "prompt_version": "none",
                "schema_version": plan.schema_version,
            },
            "fallback_reason": fallback_reason,
            "warnings": [
                "DeepSeek was unavailable or returned unusable output; this plan is a "
                "deterministic low-confidence fallback and requires approval."
            ],
            "phase": "plan_fallback_proposed",
        }


def initial_planning_state(
    *,
    run_id: str,
    thread_id: str,
    brief_payload: Mapping[str, Any],
    max_model_calls: int = 2,
    max_total_tokens: int = 12_000,
    graph_topology_version: str = PLANNING_GRAPH_TOPOLOGY_VERSION,
    state_schema_version: str = PLANNING_STATE_SCHEMA_VERSION,
) -> PlanningSubgraphState:
    """Create compact JSON-safe state for a finite planning-only run."""

    if not 1 <= max_model_calls <= 4:
        raise ValueError("max_model_calls must be between 1 and 4")
    if not 256 <= max_total_tokens <= 100_000:
        raise ValueError("max_total_tokens must be between 256 and 100000")
    return PlanningSubgraphState(
        run_id=run_id,
        thread_id=thread_id,
        graph_topology_version=graph_topology_version,
        state_schema_version=state_schema_version,
        brief_payload=dict(brief_payload),
        phase="received",
        budget={"max_model_calls": max_model_calls, "max_total_tokens": max_total_tokens},
        counters={"model_calls": 0, "total_tokens": 0},
        repair_attempts=0,
    )


def error_update(
    state: PlanningSubgraphState,
    *,
    node: str,
    category: Literal["input", "model_provider", "schema", "approval", "internal"],
    code: str,
    summary: str,
    retryable: bool,
    suggested_route: Literal["retry", "repair", "fallback", "human", "terminal"],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    envelope = AgentErrorEnvelope(
        run_id=state["run_id"],
        node=node,
        category=category,
        code=code,
        safe_summary=summary,
        retryable=retryable,
        provider=provider,
        model=model,
        schema_version=state["state_schema_version"],
        graph_topology_version=state["graph_topology_version"],
        suggested_route=suggested_route,
        attempt=state.get("counters", {}).get("model_calls", 0),
    )
    return {"phase": "error_routing", "error": envelope.model_dump(mode="json")}


def safe_validation_issues(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in issue['loc'])}:{issue['type']}"
        for issue in exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:12]
    ]


def has_error(state: PlanningSubgraphState) -> Literal["error", "continue"]:
    return "error" if state.get("error") is not None else "continue"


def plan_validation_route(
    state: PlanningSubgraphState,
) -> Literal["complete", "repair", "error"]:
    if state.get("error") is not None:
        return "error"
    if state.get("phase") == "plan_repair_needed":
        return "repair"
    return "complete"


def error_route(
    state: PlanningSubgraphState,
) -> Literal["repair", "fallback", "human", "terminal"]:
    return cast(
        Literal["repair", "fallback", "human", "terminal"],
        state.get("error_route", "terminal"),
    )


def planning_terminal_route(
    state: PlanningSubgraphState,
) -> Literal["fallback", "terminal"]:
    error = state.get("error") or {}
    if error.get("code") == "PLAN_SCHEMA_INVALID" and state["repair_attempts"] >= 1:
        return "fallback"
    return "terminal"


async def planning_complete(state: PlanningSubgraphState) -> PlanningResult:
    result = PlanningResult(
        phase="planning_complete",
        counters=dict(state["counters"]),
    )
    result["plan"] = cast(dict[str, object], dict(state["plan"]))
    if "provider_metadata" in state:
        result["provider_metadata"] = dict(state["provider_metadata"])
    if "usage" in state:
        result["usage"] = dict(state["usage"])
    if "fallback_reason" in state:
        result["fallback_reason"] = state["fallback_reason"]
    if "warnings" in state:
        result["warnings"] = list(state["warnings"])
    return result


async def planning_failed(state: PlanningSubgraphState) -> PlanningResult:
    result = PlanningResult(
        phase="planning_failed",
        counters=dict(state["counters"]),
    )
    error = state.get("error")
    if error is not None:
        result["error"] = cast(dict[str, object], dict(error))
    if "provider_metadata" in state:
        result["provider_metadata"] = dict(state["provider_metadata"])
    if "usage" in state:
        result["usage"] = dict(state["usage"])
    if "warnings" in state:
        result["warnings"] = list(state["warnings"])
    return result


def add_planning_nodes_and_edges(
    graph: Any,
    nodes: PlanningNodes,
    *,
    complete_target: str,
    fallback_target: str,
    human_error_target: str,
    terminal_target: str,
) -> None:
    """Mount the shared planning nodes without approval or persistence side effects."""

    graph.add_node("ValidateBrief", nodes.validate_brief)
    graph.add_node("CompositionPlanner", nodes.composition_planner)
    graph.add_node("ValidatePlan", nodes.validate_plan)
    graph.add_node("RepairPlan", nodes.repair_plan)
    graph.add_node("ErrorRouter", nodes.error_router)
    graph.add_node("DeterministicPlanFallback", nodes.deterministic_fallback)

    graph.add_edge(START, "ValidateBrief")
    graph.add_conditional_edges(
        "ValidateBrief", has_error, {"continue": "CompositionPlanner", "error": "ErrorRouter"}
    )
    graph.add_conditional_edges(
        "CompositionPlanner",
        has_error,
        {"continue": "ValidatePlan", "error": "ErrorRouter"},
    )
    graph.add_conditional_edges(
        "ValidatePlan",
        plan_validation_route,
        {"complete": complete_target, "repair": "RepairPlan", "error": "ErrorRouter"},
    )
    graph.add_conditional_edges(
        "RepairPlan", has_error, {"continue": "ValidatePlan", "error": "ErrorRouter"}
    )
    graph.add_conditional_edges(
        "ErrorRouter",
        error_route,
        {
            "repair": "RepairPlan",
            "fallback": fallback_target,
            "human": human_error_target,
            "terminal": terminal_target,
        },
    )
    graph.add_conditional_edges(
        "DeterministicPlanFallback",
        has_error,
        {"continue": "ValidatePlan", "error": "ErrorRouter"},
    )


def build_composition_planning_subgraph(
    planner: CompositionPlanner,
    *,
    telemetry: TelemetryRecorder | None = None,
) -> CompiledStateGraph[PlanningSubgraphState, None, PlanningSubgraphState, PlanningResult]:
    """Compile a finite planning-only graph with no interrupts or write side effects."""

    graph = StateGraph(
        PlanningSubgraphState,
        input_schema=PlanningSubgraphState,
        output_schema=PlanningResult,
    )
    nodes = PlanningNodes(planner, telemetry)

    async def planning_fallback_route(state: PlanningSubgraphState) -> dict[str, Any]:
        del state
        return {}

    async def planning_terminal_router(state: PlanningSubgraphState) -> dict[str, Any]:
        if planning_terminal_route(state) == "fallback":
            return {"fallback_reason": "PLAN_SCHEMA_INVALID_AFTER_REPAIR"}
        return {}

    graph.add_node("PlanningComplete", planning_complete)
    graph.add_node("PlanningFailed", planning_failed)
    graph.add_node("PlanningFallbackRoute", planning_fallback_route)
    graph.add_node("PlanningTerminalRouter", planning_terminal_router)
    add_planning_nodes_and_edges(
        graph,
        nodes,
        complete_target="PlanningComplete",
        fallback_target="DeterministicPlanFallback",
        human_error_target="PlanningFallbackRoute",
        terminal_target="PlanningTerminalRouter",
    )
    graph.add_conditional_edges(
        "PlanningFallbackRoute",
        lambda state: "fallback" if state.get("brief") is not None else "terminal",
        {"fallback": "DeterministicPlanFallback", "terminal": "PlanningFailed"},
    )
    graph.add_conditional_edges(
        "PlanningTerminalRouter",
        planning_terminal_route,
        {"fallback": "DeterministicPlanFallback", "terminal": "PlanningFailed"},
    )
    graph.add_edge("PlanningComplete", END)
    graph.add_edge("PlanningFailed", END)
    return graph.compile(name="CompositionPlanningSubgraph")
