from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from motif_forge.agent.generate import GenerateRequest, initial_generate_state
from motif_forge.agent.graph import build_composition_plan_graph, initial_plan_state
from motif_forge.agent.parent_graph import (
    PARENT_TIME_STRETCH_RUN_TYPE,
    build_parent_graph,
    initial_time_stretch_state,
)
from motif_forge.agent.planner import PlannerError, StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.generation import (
    CompleteExportCursor,
    MaterializeApprovedCompositionResult,
    PersistPlanningResultResult,
)
from motif_forge.application.media_jobs import EnqueueMediaJobRequest, EnqueueMediaJobResult
from motif_forge.domain.ai_runs import AIRunApproval, composition_plan_content_hash
from motif_forge.domain.media_jobs import JobStatus, TimeStretchJobPayload
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.worker.outbox import OutboxMessage, ParentGraphResumePublisher

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


class _FixedEnqueuer:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.job_id = uuid4()
        self.calls = 0

    async def __call__(self, request: EnqueueMediaJobRequest) -> EnqueueMediaJobResult:
        del request
        self.calls += 1
        return EnqueueMediaJobResult(
            run_id=self.run_id,
            job_id=self.job_id,
            status=JobStatus.QUEUED,
        )


class _FailingEnqueuer:
    async def __call__(self, request: EnqueueMediaJobRequest) -> EnqueueMediaJobResult:
        del request
        raise AssertionError("enqueue must not rerun after Parent Graph checkpoint recovery")


class _RestartPersist:
    def __init__(self) -> None:
        self.calls = 0
        self.plan_id = uuid4()

    async def __call__(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        plan = CompositionPlan.model_validate_json(
            json.dumps(request.planning_result["plan"]), strict=True
        )
        return PersistPlanningResultResult(
            run_id=request.run_id,
            plan_id=self.plan_id,
            plan_hash=composition_plan_content_hash(plan),
            interrupt_ref="postgres-generate-approval-v1",
            run_version=1,
        )


class _RestartApproval:
    async def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        return AIRunApproval(
            approval_id=uuid4(),
            run_id=kwargs["run_id"],
            assertion_hash="a" * 64,
            decision=kwargs["decision"],
            actor_id=kwargs["actor_id"],
            expected_plan_content_hash=kwargs["expected_plan_content_hash"],
            interrupt_ref=kwargs["interrupt_ref"],
            decided_at=datetime.now(UTC),
        )


class _RestartMaterialize:
    def __init__(self) -> None:
        self.calls = 0
        self.revision_id = uuid4()

    async def __call__(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return MaterializeApprovedCompositionResult(
            status="approved", plan_id=request.plan_id, revision_id=self.revision_id
        )


class _RestartExport:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.job_id = uuid4()
        self.calls = 0

    async def enqueue(self, cursor: CompleteExportCursor) -> CompleteExportCursor:
        self.calls += 1
        return cursor.model_copy(
            update={
                "media_run_id": self.run_id,
                "pending_job_id": self.job_id,
                "pending_idempotency_key": "postgres-export-step-0",
            }
        )

    async def collect(self, cursor: CompleteExportCursor, **kwargs):  # type: ignore[no-untyped-def]
        del cursor, kwargs
        raise AssertionError("restart boundary stops before worker completion")


class _MustNotRun:
    async def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise AssertionError("persist/materialize/enqueue must not replay after restart")


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


@pytest.mark.asyncio
async def test_parent_worker_resume_survives_restart_without_reenqueue(
    test_postgres_dsn: str,
    isolated_postgres_schemas: IsolatedPostgresSchemas,
) -> None:
    thread_id = f"parent-resume-{uuid4().hex}"
    config = _config(thread_id)
    enqueuer = _FixedEnqueuer()

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as first_saver:
        graph = build_parent_graph(enqueuer, checkpointer=first_saver)
        interrupted = await graph.ainvoke(
            initial_time_stretch_state(
                thread_id=thread_id,
                project_id=uuid4(),
                request=TimeStretchJobPayload(
                    source_artifact_id=uuid4(),
                    source_bpm=120,
                    target_bpm=100,
                ),
            ),
            config,
        )
        assert interrupted["phase"] == "waiting_worker"
        assert enqueuer.calls == 1

    artifact_id = uuid4()
    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as reopened_saver:
        reopened_graph = build_parent_graph(_FailingEnqueuer(), checkpointer=reopened_saver)
        publisher = ParentGraphResumePublisher(reopened_graph)
        await publisher.publish(
            OutboxMessage(
                event_id=uuid4(),
                topic="graph.resume.requested",
                dedupe_key=f"resume:{uuid4()}",
                payload={
                    "schema_version": "worker-resume.v1",
                    "run_id": str(enqueuer.run_id),
                    "thread_id": thread_id,
                    "run_type": PARENT_TIME_STRETCH_RUN_TYPE,
                    "resume_event_id": "worker-complete-after-restart",
                    "job_id": str(enqueuer.job_id),
                    "status": "succeeded",
                    "artifact_id": str(artifact_id),
                    "error_code": None,
                },
                attempts=1,
            )
        )
        await publisher.publish(
            OutboxMessage(
                event_id=uuid4(),
                topic="graph.resume.requested",
                dedupe_key=f"resume-replay:{uuid4()}",
                payload={
                    "schema_version": "worker-resume.v1",
                    "run_id": str(enqueuer.run_id),
                    "thread_id": thread_id,
                    "run_type": PARENT_TIME_STRETCH_RUN_TYPE,
                    "resume_event_id": "worker-complete-after-restart",
                    "job_id": str(enqueuer.job_id),
                    "status": "succeeded",
                    "artifact_id": str(artifact_id),
                    "error_code": None,
                },
                attempts=2,
            )
        )
        snapshot = await reopened_graph.aget_state(config)

    assert snapshot.values["terminal_status"] == "succeeded"
    assert snapshot.values["artifact_refs"] == [str(artifact_id)]


@pytest.mark.asyncio
async def test_generate_restart_after_approval_does_not_replan_or_rematerialize(
    test_postgres_dsn: str,
    isolated_postgres_schemas: IsolatedPostgresSchemas,
) -> None:
    thread_id = f"generate-restart-{uuid4().hex}"
    config = _config(thread_id)
    persist = _RestartPersist()
    approval = _RestartApproval()
    materialize = _RestartMaterialize()
    export = _RestartExport()
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    request = GenerateRequest(
        run_id=uuid4(),
        project_id=uuid4(),
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        brief=CompositionBrief.model_validate_json(
            json.dumps(valid_brief_payload()), strict=True
        ),
        seed=91,
    )

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as first_saver:
        graph = build_parent_graph(
            _FailingEnqueuer(),
            checkpointer=first_saver,
            generate_planner=StaticCompositionPlanner(plan),
            persist_planning_result=persist,
            record_plan_approval=approval,
            materialize_approved_composition=materialize,
            enqueue_next_complete_export_job=export.enqueue,
            collect_complete_export_artifact=export.collect,
        )
        waiting = await graph.ainvoke(
            initial_generate_state(thread_id=thread_id, request=request), config
        )
        assert waiting["phase"] == "waiting_plan_approval"
        assert persist.calls == 1
        assert materialize.calls == export.calls == 0

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as reopened_saver:
        reopened = build_parent_graph(
            _FailingEnqueuer(),
            checkpointer=reopened_saver,
            generate_planner=_must_not_run_planner(),
            persist_planning_result=_MustNotRun(),
            record_plan_approval=approval,
            materialize_approved_composition=materialize,
            enqueue_next_complete_export_job=export.enqueue,
            collect_complete_export_artifact=export.collect,
        )
        approved = await reopened.ainvoke(
            Command(
                resume={
                    "decision": "approve",
                    "actor_id": "postgres-test",
                    "approval_assertion": "I authorize this exact persisted plan.",
                    "expected_plan_hash": waiting["plan_hash"],
                    "note": "restart boundary",
                }
            ),
            config,
        )
        assert approved["phase"] == "waiting_generate_worker"
        assert persist.calls == materialize.calls == export.calls == 1
        snapshot = await reopened.aget_state(config)

    assert snapshot.values["phase"] == "waiting_generate_worker"
    assert snapshot.values["pending_job_id"] == str(export.job_id)
    assert snapshot.values["materialized_revision_id"] == str(materialize.revision_id)
    assert snapshot.values["export_cursor"]["pending_job_id"] == str(export.job_id)
    assert persist.calls == materialize.calls == export.calls == 1
