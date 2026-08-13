from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from motif_forge.api.ai_runs import format_sse_event
from motif_forge.api.app import create_app
from motif_forge.application.ai_runs import CreateAIRun, CreateAIRunRequest, RecordAIRunEvent
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.config import Settings
from motif_forge.domain.ai_runs import AIRunEvent, AIRunStatus
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from sqlalchemy import text


def test_sse_event_has_persistent_sequence_id_event_and_json_data() -> None:
    event = AIRunEvent(
        sequence=13, event_id=uuid4(), run_id=uuid4(), event_type="plan.persisted",
        phase="waiting_plan_approval", payload={"safe": True}, dedupe_key="plan",
    )
    encoded = format_sse_event(event)
    assert encoded.startswith("id: 13\nevent: plan.persisted\ndata: ")
    assert '"sequence":13' in encoded
    assert encoded.endswith("\n\n")


@pytest.mark.asyncio
async def test_persistent_sse_replays_after_last_id_across_app_recreation(
    test_postgres_dsn: str,
) -> None:
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name=f"SSE {uuid4().hex}", actor_id="sse-test",
            idempotency_key=f"sse-project-{uuid4().hex}",
        )
    )
    uow = PostgresAIRunUnitOfWork(sessions)
    run = await CreateAIRun(uow)(CreateAIRunRequest.model_validate({
        "project_id": project.project_id, "branch_id": project.active_branch_id,
        "base_revision_id": project.root_revision_id, "thread_id": f"sse-{uuid4().hex}",
        "brief": {
            "title": "SSE", "purpose": "Persistent stream test",
            "style": "synth_ambient", "duration_seconds": 60, "moods": ("calm",),
        },
        "idempotency_key": f"sse-run-{uuid4().hex}",
    }))
    try:
        persisted: list[AIRunEvent] = []
        for sequence in range(2, 15):
            terminal = sequence == 14
            persisted.append(await RecordAIRunEvent(uow)(AIRunEvent(
                sequence=sequence, event_id=uuid4(), run_id=run.run_id,
                event_type="run.completed" if terminal else "run.progress",
                phase="succeeded" if terminal else "planning",
                payload={"sequence": sequence}, dedupe_key=f"sse-{sequence}",
            )))
        async with uow() as transaction:
            await transaction._session.execute(  # type: ignore[attr-defined]
                text(
                    "UPDATE app.ai_runs SET status=:status, version=version+1, "
                    "terminal_at=:terminal_at WHERE id=:run_id"
                ),
                {"status": AIRunStatus.SUCCEEDED.value, "terminal_at": datetime.now(UTC),
                 "run_id": run.run_id},
            )
        settings = Settings(postgres_dsn=test_postgres_dsn)
        replay_after = persisted[-3].sequence
        expected = (persisted[-2].sequence, persisted[-1].sequence)
        for _ in range(2):
            app = create_app(settings)
            transport = httpx.ASGITransport(app=app)
            async with (
                httpx.AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream(
                    "GET", f"/api/v1/runs/{run.run_id}/events",
                    headers={"Last-Event-ID": str(replay_after)},
                ) as response,
            ):
                body = await asyncio.wait_for(response.aread(), timeout=3)
            text_body = body.decode()
            first, second = (f"id: {value}\n" for value in expected)
            assert first in text_body and second in text_body
            assert f"id: {replay_after}\n" not in text_body
            assert text_body.index(first) < text_body.index(second)
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.projects WHERE id=:project_id"),
                {"project_id": project.project_id},
            )
        await engine.dispose()
