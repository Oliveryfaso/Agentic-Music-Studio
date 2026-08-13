"""Standalone CompositionPlan v3 regression wrapper."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from motif_forge.agent.planner import CompositionPlanner
from motif_forge.agent.planning_subgraph import (
    PLANNING_GRAPH_TOPOLOGY_VERSION,
    PLANNING_STATE_SCHEMA_VERSION,
    PlanningNodes,
    PlanningSubgraphState,
    add_planning_nodes_and_edges,
    error_update,
    initial_planning_state,
)
from motif_forge.agent.schemas import ApprovalDecision, CompositionPlan, ErrorRecoveryDecision
from motif_forge.observability.models import TelemetryRecorder

GRAPH_TOPOLOGY_VERSION = PLANNING_GRAPH_TOPOLOGY_VERSION
STATE_SCHEMA_VERSION = PLANNING_STATE_SCHEMA_VERSION

TerminalStatus = Literal["approved", "rejected", "failed"]
PlanGraphState = PlanningSubgraphState


def initial_plan_state(
    *,
    run_id: str,
    thread_id: str,
    brief_payload: Mapping[str, Any],
    max_model_calls: int = 2,
    max_total_tokens: int = 12_000,
) -> PlanGraphState:
    """Create the legacy Plan v3 state using the shared planning contract."""

    return initial_planning_state(
        run_id=run_id,
        thread_id=thread_id,
        brief_payload=brief_payload,
        max_model_calls=max_model_calls,
        max_total_tokens=max_total_tokens,
        graph_topology_version=GRAPH_TOPOLOGY_VERSION,
        state_schema_version=STATE_SCHEMA_VERSION,
    )


def _approval_route(state: PlanGraphState) -> Literal["finalize", "reject", "error"]:
    if state.get("error") is not None:
        return "error"
    decision = state.get("approval", {}).get("decision")
    return "finalize" if decision == "approve" else "reject"


def build_composition_plan_graph(
    planner: CompositionPlanner,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> CompiledStateGraph[PlanGraphState, None, PlanGraphState, PlanGraphState]:
    """Compile the legacy Plan v3 approval topology from shared planning nodes."""

    nodes = PlanningNodes(planner, telemetry)

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
            return error_update(
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
    graph.add_node("PlanApproval", plan_approval)
    graph.add_node("FinalizePlan", finalize)
    graph.add_node("RejectPlan", reject)
    graph.add_node("ErrorTerminal", error_terminal)
    graph.add_node("ErrorHuman", error_human)
    add_planning_nodes_and_edges(
        graph,
        nodes,
        complete_target="PlanApproval",
        fallback_target="DeterministicPlanFallback",
        human_error_target="ErrorHuman",
        terminal_target="ErrorTerminal",
    )
    graph.add_conditional_edges(
        "PlanApproval",
        _approval_route,
        {"finalize": "FinalizePlan", "reject": "RejectPlan", "error": "ErrorRouter"},
    )
    graph.add_conditional_edges(
        "ErrorHuman",
        human_error_route,
        {"fallback": "DeterministicPlanFallback", "terminal": "ErrorTerminal"},
    )
    graph.add_edge("FinalizePlan", END)
    graph.add_edge("RejectPlan", END)
    graph.add_edge("ErrorTerminal", END)
    return graph.compile(checkpointer=checkpointer)
