"""The first finite MotifForgeGraph production slice."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, NotRequired, TypedDict, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.planner import CompositionPlanner, PlannerError
from motif_forge.agent.schemas import (
    AgentErrorEnvelope,
    ApprovalDecision,
    CompositionBrief,
    CompositionPlan,
    ErrorRecoveryDecision,
)
from motif_forge.domain.error_policy import ErrorFacts, classify_agent_error
from motif_forge.observability.models import (
    ModelCallRecord,
    NullTelemetryRecorder,
    TelemetryRecorder,
)

GRAPH_TOPOLOGY_VERSION = "motif-forge-plan.v3"
STATE_SCHEMA_VERSION = "motif-forge-plan-state.v3"

TerminalStatus = Literal["approved", "rejected", "failed"]


class PlanGraphState(TypedDict):
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
    human_error_decision: NotRequired[dict[str, str]]
    warnings: NotRequired[list[str]]
    terminal_status: NotRequired[TerminalStatus]


def initial_plan_state(
    *,
    run_id: str,
    thread_id: str,
    brief_payload: Mapping[str, Any],
    max_model_calls: int = 2,
    max_total_tokens: int = 12_000,
) -> PlanGraphState:
    """Create the compact state for one finite generation-planning run."""

    if not 1 <= max_model_calls <= 4:
        raise ValueError("max_model_calls must be between 1 and 4")
    if not 256 <= max_total_tokens <= 100_000:
        raise ValueError("max_total_tokens must be between 256 and 100000")

    return PlanGraphState(
        run_id=run_id,
        thread_id=thread_id,
        graph_topology_version=GRAPH_TOPOLOGY_VERSION,
        state_schema_version=STATE_SCHEMA_VERSION,
        brief_payload=dict(brief_payload),
        phase="received",
        budget={"max_model_calls": max_model_calls, "max_total_tokens": max_total_tokens},
        counters={"model_calls": 0, "total_tokens": 0},
        repair_attempts=0,
    )


def _error_update(
    state: PlanGraphState,
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


def _has_error(state: PlanGraphState) -> Literal["error", "continue"]:
    return "error" if state.get("error") is not None else "continue"


def _approval_route(state: PlanGraphState) -> Literal["finalize", "reject", "error"]:
    if state.get("error") is not None:
        return "error"
    decision = state.get("approval", {}).get("decision")
    return "finalize" if decision == "approve" else "reject"


def _plan_validation_route(
    state: PlanGraphState,
) -> Literal["approval", "repair", "error"]:
    if state.get("error") is not None:
        return "error"
    if state.get("phase") == "plan_repair_needed":
        return "repair"
    return "approval"


def _safe_validation_issues(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in issue['loc'])}:{issue['type']}"
        for issue in exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:12]
    ]


def build_composition_plan_graph(
    planner: CompositionPlanner,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> CompiledStateGraph[PlanGraphState, None, PlanGraphState, PlanGraphState]:
    """Compile ValidateBrief -> Planner -> ValidatePlan -> approval -> terminal."""

    recorder = telemetry or NullTelemetryRecorder()

    async def validate_brief(state: PlanGraphState) -> dict[str, Any]:
        try:
            brief = CompositionBrief.model_validate_json(
                json.dumps(state["brief_payload"]), strict=True
            )
        except ValidationError:
            return _error_update(
                state,
                node="ValidateBrief",
                category="input",
                code="BRIEF_SCHEMA_INVALID",
                summary="The composition brief does not match the required schema.",
                retryable=False,
                suggested_route="human",
            )
        return {"brief": brief.model_dump(mode="json"), "phase": "brief_validated"}

    async def run_planner(state: PlanGraphState, *, repair: bool) -> dict[str, Any]:
        brief_payload = state.get("brief")
        if brief_payload is None:
            return _error_update(
                state,
                node="RepairPlan" if repair else "CompositionPlanner",
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
            return _error_update(
                state,
                node="RepairPlan" if repair else "CompositionPlanner",
                category="model_provider",
                code="MODEL_CALL_BUDGET_EXHAUSTED",
                summary="The model-call budget was exhausted before planning completed.",
                retryable=False,
                suggested_route="human",
            )
        node_name = "RepairPlan" if repair else "CompositionPlanner"
        started_at = datetime.now(UTC)
        try:
            if repair:
                response = await planner.repair_plan(
                    brief,
                    invalid_payload=state.get("plan_payload", {}),
                    validation_issues=tuple(state.get("validation_issues", ())),
                )
            else:
                response = await planner.create_plan(
                    brief,
                    allow_schema_repair=(budget["max_model_calls"] - counters["model_calls"] >= 2),
                )
        except PlannerError as exc:
            ended_at = datetime.now(UTC)
            try:
                await recorder.record_model_call(
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
                return _error_update(
                    state,
                    node=node_name,
                    category="internal",
                    code="OBSERVABILITY_WRITE_FAILED",
                    summary="Model telemetry could not be persisted safely.",
                    retryable=False,
                    suggested_route="terminal",
                )
            route = cast(
                Literal["retry", "repair", "fallback", "human", "terminal"],
                exc.suggested_route,
            )
            return _error_update(
                state,
                node="RepairPlan" if repair else "CompositionPlanner",
                category="model_provider",
                code=exc.code,
                summary=exc.safe_summary,
                retryable=exc.retryable,
                suggested_route=route,
                provider="deepseek",
                model="deepseek-v4-flash",
            )
        except Exception:
            return _error_update(
                state,
                node="RepairPlan" if repair else "CompositionPlanner",
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
            await recorder.record_model_call(
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
            return _error_update(
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
                _error_update(
                    {**state, "counters": next_counters},
                    node="RepairPlan" if repair else "CompositionPlanner",
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

    async def composition_planner(state: PlanGraphState) -> dict[str, Any]:
        return await run_planner(state, repair=False)

    async def repair_plan(state: PlanGraphState) -> dict[str, Any]:
        return await run_planner(state, repair=True)

    async def validate_plan(state: PlanGraphState) -> dict[str, Any]:
        payload = state.get("plan_payload")
        if payload is None:
            return _error_update(
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
                    return _error_update(
                        state,
                        node="ValidatePlan",
                        category="schema",
                        code="SCHEMA_REPAIR_BUDGET_EXHAUSTED",
                        summary="The plan is invalid and no model-call budget remains for repair.",
                        retryable=False,
                        suggested_route="human",
                        provider=state.get("provider_metadata", {}).get("provider"),
                        model=state.get("provider_metadata", {}).get("model"),
                    )
                return {
                    "phase": "plan_repair_needed",
                    "validation_issues": _safe_validation_issues(exc),
                }
            return _error_update(
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

    async def plan_approval(state: PlanGraphState) -> dict[str, Any]:
        plan = CompositionPlan.model_validate_json(json.dumps(state["plan"]), strict=True)
        approval_payload = {
            "interrupt_version": "plan-approval.v1",
            "run_id": state["run_id"],
            "plan_summary": {
                "genre": plan.genre,
                "duration_bars": plan.duration_bars,
                "bpm": plan.bpm,
                "meter": plan.meter,
                "key": plan.key.model_dump(mode="json"),
                "sections": [section.name for section in plan.sections],
                "instruments": [item.name for item in plan.instrumentation],
                "confidence": plan.confidence,
            },
            "options": ["approve", "reject"],
            "warnings": state.get("warnings", []),
        }
        resumed_value = interrupt(approval_payload)
        try:
            decision = ApprovalDecision.model_validate_json(json.dumps(resumed_value), strict=True)
        except ValidationError:
            return _error_update(
                state,
                node="PlanApproval",
                category="approval",
                code="APPROVAL_DECISION_INVALID",
                summary="The plan approval decision is invalid.",
                retryable=False,
                suggested_route="human",
            )
        return {"approval": decision.model_dump(mode="json"), "phase": "plan_decided"}

    async def finalize(state: PlanGraphState) -> dict[str, Any]:
        del state
        return {"phase": "complete", "terminal_status": "approved"}

    async def reject(state: PlanGraphState) -> dict[str, Any]:
        del state
        return {"phase": "complete", "terminal_status": "rejected"}

    async def error_terminal(state: PlanGraphState) -> dict[str, Any]:
        del state
        return {"phase": "complete", "terminal_status": "failed"}

    async def error_router(state: PlanGraphState) -> dict[str, Any]:
        error = state.get("error")
        if error is None:
            return _error_update(
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

    def error_route(state: PlanGraphState) -> Literal["repair", "fallback", "human", "terminal"]:
        return cast(
            Literal["repair", "fallback", "human", "terminal"],
            state.get("error_route", "terminal"),
        )

    async def deterministic_fallback(state: PlanGraphState) -> dict[str, Any]:
        brief_payload = state.get("brief")
        if brief_payload is None:
            return _error_update(
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
        return {
            "error": None,
            "plan_payload": plan.model_dump(mode="json"),
            "provider_metadata": {
                "provider": "deterministic",
                "model": "composition-template",
                "prompt_version": "none",
                "schema_version": plan.schema_version,
            },
            "warnings": [
                "DeepSeek was unavailable or returned unusable output; this plan is a "
                "deterministic low-confidence fallback and requires approval."
            ],
            "phase": "plan_fallback_proposed",
        }

    async def error_human(state: PlanGraphState) -> dict[str, Any]:
        allow_fallback = state.get("brief") is not None
        resumed = interrupt(
            {
                "interrupt_version": "agent-error-recovery.v1",
                "run_id": state["run_id"],
                "error": state.get("error"),
                "policy": state.get("error_policy"),
                "options": ["fallback", "stop"] if allow_fallback else ["stop"],
            }
        )
        try:
            decision = ErrorRecoveryDecision.model_validate_json(json.dumps(resumed), strict=True)
        except ValidationError:
            return {"human_error_decision": {"decision": "stop"}, "phase": "error_stop"}
        if decision.decision == "fallback" and not allow_fallback:
            return {"human_error_decision": {"decision": "stop"}, "phase": "error_stop"}
        return {
            "human_error_decision": decision.model_dump(mode="json"),
            "phase": "error_human_decided",
        }

    def human_error_route(state: PlanGraphState) -> Literal["fallback", "terminal"]:
        return (
            "fallback"
            if state.get("human_error_decision", {}).get("decision") == "fallback"
            else "terminal"
        )

    graph = StateGraph(PlanGraphState)
    graph.add_node("ValidateBrief", validate_brief)
    graph.add_node("CompositionPlanner", composition_planner)
    graph.add_node("ValidatePlan", validate_plan)
    graph.add_node("RepairPlan", repair_plan)
    graph.add_node("PlanApproval", plan_approval)
    graph.add_node("FinalizePlan", finalize)
    graph.add_node("RejectPlan", reject)
    graph.add_node("ErrorTerminal", error_terminal)
    graph.add_node("ErrorRouter", error_router)
    graph.add_node("ErrorHuman", error_human)
    graph.add_node("DeterministicPlanFallback", deterministic_fallback)

    graph.add_edge(START, "ValidateBrief")
    graph.add_conditional_edges(
        "ValidateBrief",
        _has_error,
        {"continue": "CompositionPlanner", "error": "ErrorRouter"},
    )
    graph.add_conditional_edges(
        "CompositionPlanner",
        _has_error,
        {"continue": "ValidatePlan", "error": "ErrorRouter"},
    )
    graph.add_conditional_edges(
        "ValidatePlan",
        _plan_validation_route,
        {
            "approval": "PlanApproval",
            "repair": "RepairPlan",
            "error": "ErrorRouter",
        },
    )
    graph.add_conditional_edges(
        "RepairPlan",
        _has_error,
        {"continue": "ValidatePlan", "error": "ErrorRouter"},
    )
    graph.add_conditional_edges(
        "PlanApproval",
        _approval_route,
        {"finalize": "FinalizePlan", "reject": "RejectPlan", "error": "ErrorRouter"},
    )
    graph.add_conditional_edges(
        "ErrorRouter",
        error_route,
        {
            "repair": "RepairPlan",
            "fallback": "DeterministicPlanFallback",
            "human": "ErrorHuman",
            "terminal": "ErrorTerminal",
        },
    )
    graph.add_conditional_edges(
        "ErrorHuman",
        human_error_route,
        {"fallback": "DeterministicPlanFallback", "terminal": "ErrorTerminal"},
    )
    graph.add_conditional_edges(
        "DeterministicPlanFallback",
        _has_error,
        {"continue": "ValidatePlan", "error": "ErrorRouter"},
    )
    graph.add_edge("FinalizePlan", END)
    graph.add_edge("RejectPlan", END)
    graph.add_edge("ErrorTerminal", END)
    return graph.compile(checkpointer=checkpointer)
