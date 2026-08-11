from __future__ import annotations

import json
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from motif_forge.agent.graph import build_composition_plan_graph, initial_plan_state
from motif_forge.agent.planner import PlannerError, StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.infrastructure.checkpoints import postgres_checkpointer

from .conftest import IsolatedPostgresSchemas
from .sample_data import valid_brief_payload, valid_plan_payload


def _planner() -> StaticCompositionPlanner:
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    return StaticCompositionPlanner(plan)


def _must_not_run_planner() -> StaticCompositionPlanner:
    return StaticCompositionPlanner(
        {},
        failure=PlannerError(
            "PLANNER_MUST_NOT_RUN_AFTER_RESUME",
            "The planner was unexpectedly called after checkpoint recovery.",
            retryable=False,
            suggested_route="terminal",
        ),
    )


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def test_integration_agent_fixtures_match_strict_v1_schemas() -> None:
    CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)
    CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)


@pytest.mark.asyncio
async def test_interrupt_survives_connection_close_and_resumes_from_postgres(
    test_postgres_dsn: str,
    isolated_postgres_schemas: IsolatedPostgresSchemas,
) -> None:
    """A human approval can resume after both graph and DB connection are recreated."""

    thread_id = f"checkpoint-resume-{uuid4().hex}"
    config = _config(thread_id)

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as first_saver:
        first_graph = build_composition_plan_graph(_planner(), checkpointer=first_saver)
        interrupted = await first_graph.ainvoke(
            initial_plan_state(
                run_id=f"run-{uuid4().hex}",
                thread_id=thread_id,
                brief_payload=valid_brief_payload(),
            ),
            config,
        )

        assert interrupted["phase"] == "plan_validated"
        assert interrupted["__interrupt__"][0].value["options"] == ["approve", "reject"]
        assert await first_saver.aget_tuple(config) is not None

    # This is deliberately a new connection, saver, graph, and planner instance. The
    # failing planner proves resume continues at the persisted approval boundary.
    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as reopened_saver:
        reopened_graph = build_composition_plan_graph(
            _must_not_run_planner(), checkpointer=reopened_saver
        )
        completed = await reopened_graph.ainvoke(
            Command(resume={"decision": "approve", "note": "Resume after restart"}),
            config,
        )

        assert completed["terminal_status"] == "approved"
        assert completed["approval"]["decision"] == "approve"
        assert completed["phase"] == "complete"


@pytest.mark.asyncio
async def test_checkpoint_rows_are_isolated_by_postgres_schema(
    test_postgres_dsn: str,
    isolated_postgres_schemas: IsolatedPostgresSchemas,
) -> None:
    """The same thread ID in another checkpoint schema cannot see persisted state."""

    thread_id = f"schema-isolation-{uuid4().hex}"
    config = _config(thread_id)

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as primary_saver:
        graph = build_composition_plan_graph(_planner(), checkpointer=primary_saver)
        interrupted = await graph.ainvoke(
            initial_plan_state(
                run_id=f"run-{uuid4().hex}",
                thread_id=thread_id,
                brief_payload=valid_brief_payload(),
            ),
            config,
        )
        assert "__interrupt__" in interrupted
        assert await primary_saver.aget_tuple(config) is not None

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.secondary
    ) as secondary_saver:
        assert await secondary_saver.aget_tuple(config) is None

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as reopened_primary_saver:
        assert await reopened_primary_saver.aget_tuple(config) is not None
