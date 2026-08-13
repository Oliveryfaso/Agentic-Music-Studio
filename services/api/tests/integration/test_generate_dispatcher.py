from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.ai_runs import (
    CreateAIRun,
    CreateAIRunRequest,
    ReadAIRun,
    RecordAIRunApproval,
    RequestAIRunAction,
)
from motif_forge.application.generation import (
    CompleteExportCursor,
    MaterializeApprovedCompositionResult,
    PersistPlanningResult,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.worker.outbox import (
    GRAPH_ACTION_TOPICS,
    ParentGraphActionPublisher,
    PostgresOutboxStore,
)
from sqlalchemy import text

from .sample_data import valid_brief_payload, valid_plan_payload


class CountingPlanner:
    def __init__(self) -> None:
        plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
        self.delegate = StaticCompositionPlanner(plan)
        self.calls = 0

    async def create_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return await self.delegate.create_plan(*args, **kwargs)

    async def repair_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await self.delegate.repair_plan(*args, **kwargs)


class Services:
    def __init__(self) -> None:
        self.plan_id = uuid4()
        self.revision_id = uuid4()
        self.media_run_id = uuid4()
        self.job_id = uuid4()
        self.materialize_calls = self.enqueue_calls = 0

    async def materialize(self, request):  # type: ignore[no-untyped-def]
        self.materialize_calls += 1
        return MaterializeApprovedCompositionResult(
            status="approved", plan_id=request.plan_id, revision_id=self.revision_id
        )

    async def enqueue(self, cursor: CompleteExportCursor) -> CompleteExportCursor:
        self.enqueue_calls += 1
        return cursor.model_copy(update={
            "media_run_id": self.media_run_id,
            "pending_job_id": self.job_id,
            "pending_idempotency_key": "dispatcher-export-master",
        })

    async def collect(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise AssertionError("worker completion is outside this dispatcher boundary")


@pytest.mark.asyncio
async def test_postgres_dispatcher_deduplicates_start_resume_and_wakes_cancel(
    test_postgres_dsn: str, isolated_postgres_schemas,
) -> None:  # type: ignore[no-untyped-def]
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE app.outbox_events SET status='published' "
                "WHERE aggregate_type='ai_run' AND status IN ('pending', 'publishing')"
            )
        )
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name=f"Dispatcher {uuid4().hex}", actor_id="dispatcher-test",
            idempotency_key=f"dispatcher-project-{uuid4().hex}",
        )
    )
    ai_uow = PostgresAIRunUnitOfWork(sessions)
    planner, services = CountingPlanner(), Services()
    store = PostgresOutboxStore(
        sessions, topics=GRAPH_ACTION_TOPICS, aggregate_type="ai_run"
    )
    try:
        run = await CreateAIRun(ai_uow)(CreateAIRunRequest(
            project_id=project.project_id, branch_id=project.active_branch_id,
            base_revision_id=project.root_revision_id,
            thread_id=f"dispatcher-{uuid4().hex}",
            brief=CompositionBrief.model_validate_json(
                json.dumps(valid_brief_payload()), strict=True
            ),
            idempotency_key=f"dispatcher-run-{uuid4().hex}",
        ))
        async with postgres_checkpointer(
            test_postgres_dsn, schema=isolated_postgres_schemas.primary
        ) as saver:
            graph = build_parent_graph(
                lambda request: None, checkpointer=saver,  # type: ignore[arg-type]
                generate_planner=planner,
                persist_planning_result=PersistPlanningResult(ai_uow),
                record_plan_approval=RecordAIRunApproval(ai_uow),
                materialize_approved_composition=services.materialize,
                enqueue_next_complete_export_job=services.enqueue,
                collect_complete_export_artifact=services.collect,
            )
            publisher = ParentGraphActionPublisher(graph, load_run=ReadAIRun(ai_uow))
            now = datetime.now(UTC)
            starts = await store.claim_batch(
                owner="dispatcher-test", now=now,
                lease_expires_at=now + timedelta(minutes=1), batch_size=1,
            )
            assert len(starts) == 1
            await publisher.publish(starts[0])
            await publisher.publish(starts[0])
            snapshot = await graph.aget_state({"configurable": {"thread_id": run.thread_id}})
            pending = await ReadAIRun(ai_uow)(run.run_id)
            await RecordAIRunApproval(ai_uow)(
                run_id=run.run_id, actor_id="dispatcher-test", decision="approve",
                assertion="I authorize this exact persisted plan.",
                expected_version=pending.version,
                expected_plan_content_hash=snapshot.values["plan_hash"],
                interrupt_ref=snapshot.values["plan_interrupt_ref"],
            )
            resumes = await store.claim_batch(
                owner="dispatcher-test", now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1), batch_size=1,
            )
            assert len(resumes) == 1
            await publisher.publish(resumes[0])
            await publisher.publish(resumes[0])
            assert planner.calls == 1
            assert services.materialize_calls == services.enqueue_calls == 1

            cancel_run = await CreateAIRun(ai_uow)(CreateAIRunRequest(
                project_id=project.project_id, branch_id=project.active_branch_id,
                base_revision_id=project.root_revision_id,
                thread_id=f"dispatcher-cancel-{uuid4().hex}",
                brief=CompositionBrief.model_validate_json(
                    json.dumps(valid_brief_payload()), strict=True
                ),
                idempotency_key=f"dispatcher-cancel-{uuid4().hex}",
            ))
            cancel_starts = await store.claim_batch(
                owner="dispatcher-test", now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1), batch_size=1,
            )
            assert len(cancel_starts) == 1
            await publisher.publish(cancel_starts[0])
            waiting_cancel = await ReadAIRun(ai_uow)(cancel_run.run_id)
            await RequestAIRunAction(ai_uow)(
                run_id=cancel_run.run_id, action="cancel",
                expected_version=waiting_cancel.version,
                idempotency_key="dispatcher-authoritative-cancel",
            )
            cancels = await store.claim_batch(
                owner="dispatcher-test", now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1), batch_size=1,
            )
            assert len(cancels) == 1
            await publisher.publish(cancels[0])
            cancelled = await graph.aget_state({
                "configurable": {"thread_id": cancel_run.thread_id}
            })
            assert cancelled.values["terminal_status"] == "cancelled"
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
