"""The first finite MotifForgeGraph production slice."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, NotRequired, TypedDict, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from motif_forge.agent.planner import CompositionPlanner, PlannerError
from motif_forge.agent.schemas import (
    AgentErrorEnvelope,
    ApprovalDecision,
    CompositionBrief,
    CompositionPlan,
)

GRAPH_TOPOLOGY_VERSION = "motif-forge-plan.v1"
STATE_SCHEMA_VERSION = "motif-forge-plan-state.v1"

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
    approval: NotRequired[dict[str, str]]
    error: NotRequired[dict[str, Any]]
    terminal_status: NotRequired[TerminalStatus]


def initial_plan_state(
    *, run_id: str, thread_id: str, brief_payload: Mapping[str, Any]
) -> PlanGraphState:
    """Create the compact state for one finite generation-planning run."""

    return PlanGraphState(
        run_id=run_id,
        thread_id=thread_id,
        graph_topology_version=GRAPH_TOPOLOGY_VERSION,
        state_schema_version=STATE_SCHEMA_VERSION,
        brief_payload=dict(brief_payload),
        phase="received",
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
    )
    return {"phase": "error_routing", "error": envelope.model_dump(mode="json")}


def _has_error(state: PlanGraphState) -> Literal["error", "continue"]:
    return "error" if "error" in state else "continue"


def _approval_route(state: PlanGraphState) -> Literal["finalize", "reject", "error"]:
    if "error" in state:
        return "error"
    decision = state.get("approval", {}).get("decision")
    return "finalize" if decision == "approve" else "reject"


def build_composition_plan_graph(
    planner: CompositionPlanner,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[PlanGraphState, None, PlanGraphState, PlanGraphState]:
    """Compile ValidateBrief -> Planner -> ValidatePlan -> approval -> terminal."""

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

    async def composition_planner(state: PlanGraphState) -> dict[str, Any]:
        brief_payload = state.get("brief")
        if brief_payload is None:
            return _error_update(
                state,
                node="CompositionPlanner",
                category="internal",
                code="VALIDATED_BRIEF_MISSING",
                summary="The validated composition brief is unavailable.",
                retryable=False,
                suggested_route="terminal",
            )
        brief = CompositionBrief.model_validate_json(json.dumps(brief_payload), strict=True)
        try:
            response = await planner.create_plan(brief)
        except PlannerError as exc:
            route = cast(
                Literal["retry", "repair", "fallback", "human", "terminal"],
                exc.suggested_route,
            )
            return _error_update(
                state,
                node="CompositionPlanner",
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
                node="CompositionPlanner",
                category="internal",
                code="PLANNER_UNEXPECTED_FAILURE",
                summary="The composition planner failed unexpectedly.",
                retryable=False,
                suggested_route="terminal",
            )
        return {
            "plan_payload": dict(response.plan_payload),
            "provider_metadata": {
                "provider": response.provider,
                "model": response.model,
                "prompt_version": response.prompt_version,
                "schema_version": response.schema_version,
            },
            "usage": response.usage.as_dict(),
            "phase": "plan_proposed",
        }

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
        except ValidationError:
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

    graph = StateGraph(PlanGraphState)
    graph.add_node("ValidateBrief", validate_brief)
    graph.add_node("CompositionPlanner", composition_planner)
    graph.add_node("ValidatePlan", validate_plan)
    graph.add_node("PlanApproval", plan_approval)
    graph.add_node("FinalizePlan", finalize)
    graph.add_node("RejectPlan", reject)
    graph.add_node("ErrorTerminal", error_terminal)

    graph.add_edge(START, "ValidateBrief")
    graph.add_conditional_edges(
        "ValidateBrief",
        _has_error,
        {"continue": "CompositionPlanner", "error": "ErrorTerminal"},
    )
    graph.add_conditional_edges(
        "CompositionPlanner",
        _has_error,
        {"continue": "ValidatePlan", "error": "ErrorTerminal"},
    )
    graph.add_conditional_edges(
        "ValidatePlan",
        _has_error,
        {"continue": "PlanApproval", "error": "ErrorTerminal"},
    )
    graph.add_conditional_edges(
        "PlanApproval",
        _approval_route,
        {"finalize": "FinalizePlan", "reject": "RejectPlan", "error": "ErrorTerminal"},
    )
    graph.add_edge("FinalizePlan", END)
    graph.add_edge("RejectPlan", END)
    graph.add_edge("ErrorTerminal", END)
    return graph.compile(checkpointer=checkpointer)
