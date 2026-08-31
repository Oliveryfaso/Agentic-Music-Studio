from __future__ import annotations

from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.infrastructure.persistence.database import (
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.run_graph_history import (
    PostgresRunGraphHistoryStore,
)
from psycopg import AsyncConnection

from .conftest import IsolatedPostgresSchemas


class TinyState(TypedDict, total=False):
    steps: tuple[str, ...]


@pytest.mark.asyncio
async def test_real_langgraph_task_paths_are_read_repeatably_without_payloads(
    test_postgres_dsn: str,
    isolated_postgres_schemas: IsolatedPostgresSchemas,
) -> None:
    thread_id = f"graph-read-{uuid4().hex}"
    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as checkpointer:
        builder = StateGraph(TinyState)
        builder.add_node("Alpha", lambda state: {"steps": (*state.get("steps", ()), "a")})
        builder.add_node("Beta", lambda state: {"steps": (*state.get("steps", ()), "b")})
        builder.add_edge(START, "Alpha")
        builder.add_edge("Alpha", "Beta")
        builder.add_edge("Beta", END)
        graph = builder.compile(checkpointer=checkpointer)
        await graph.ainvoke({"steps": ()}, {"configurable": {"thread_id": thread_id}})

    connection = await AsyncConnection.connect(test_postgres_dsn)
    async with connection:
        columns = await connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name='checkpoint_writes'",
            (isolated_postgres_schemas.primary,),
        )
        assert "task_path" in {row[0] async for row in columns}

    engine = create_postgres_engine(test_postgres_dsn)
    try:
        sessions = create_session_factory(engine)
        store = PostgresRunGraphHistoryStore(sessions, schema=isolated_postgres_schemas.primary)
        first = await store.read_run_graph_history(thread_id)
        second = await store.read_run_graph_history(thread_id)

        assert first == second
        assert first.schema_compatible is True
        assert first.checkpoint_count > 0
        assert {item.technical_name for item in first.task_paths} >= {"Alpha", "Beta"}
        serialized = first.model_dump_json()
        for forbidden in ("blob", "channel", "metadata", "payload", "messages", "state"):
            assert forbidden not in serialized

        incompatible = await PostgresRunGraphHistoryStore(
            sessions, schema=isolated_postgres_schemas.secondary
        ).read_run_graph_history(thread_id)
        assert incompatible.schema_compatible is False
        assert incompatible.task_paths == ()
    finally:
        await engine.dispose()
