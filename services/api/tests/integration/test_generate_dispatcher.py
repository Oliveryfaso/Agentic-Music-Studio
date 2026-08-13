from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from motif_forge.agent.generate import PlanApprovalDecision
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.generation import (
    CompleteExportCursor,
    MaterializeApprovedCompositionResult,
    PersistPlanningResultResult,
)
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunApproval,
    AIRunStatus,
    composition_plan_content_hash,
)
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.worker.outbox import OutboxMessage, ParentGraphActionPublisher

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
        self.persist_calls = self.approval_calls = self.materialize_calls = self.enqueue_calls = 0

    async def persist(self, request):  # type: ignore[no-untyped-def]
        self.persist_calls += 1
        plan = CompositionPlan.model_validate_json(
            json.dumps(request.planning_result["plan"]), strict=True
        )
        return PersistPlanningResultResult(
            run_id=request.run_id,
            plan_id=self.plan_id,
            plan_hash=composition_plan_content_hash(plan),
            interrupt_ref="dispatcher-plan-interrupt-v1",
            run_version=1,
        )

    async def approve(self, **kwargs):  # type: ignore[no-untyped-def]
        self.approval_calls += 1
        return AIRunApproval(
            approval_id=uuid4(), run_id=kwargs["run_id"], assertion_hash="a" * 64,
            decision=kwargs["decision"], actor_id=kwargs["actor_id"],
            expected_plan_content_hash=kwargs["expected_plan_content_hash"],
            interrupt_ref=kwargs["interrupt_ref"], decided_at=datetime.now(UTC),
        )

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


class RunLoader:
    def __init__(self, run: AIRun) -> None:
        self.run = run

    async def __call__(self, run_id):  # type: ignore[no-untyped-def]
        assert run_id == self.run.run_id
        return self.run


def action(
    run: AIRun,
    action_name: str,
    decision: PlanApprovalDecision | None = None,
) -> OutboxMessage:
    return OutboxMessage(
        event_id=uuid4(), topic=f"graph.{action_name}.requested",
        dedupe_key=f"{action_name}:{run.run_id}", attempts=1,
        payload={
            "schema_version": "graph-action.v1", "action": action_name,
            "run_id": str(run.run_id), "thread_id": run.thread_id,
            "run_type": "parent.generate.v1",
            "decision": None if decision is None else decision.model_dump(mode="json"),
        },
    )


@pytest.mark.asyncio
async def test_postgres_dispatcher_deduplicates_start_resume_and_wakes_cancel(
    test_postgres_dsn: str, isolated_postgres_schemas,
) -> None:  # type: ignore[no-untyped-def]
    brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)
    run = AIRun(
        run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
        thread_id=f"dispatcher-{uuid4().hex}", brief=brief.model_dump(mode="json"),
    )
    planner, services, loader = CountingPlanner(), Services(), RunLoader(run)
    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as saver:
        graph = build_parent_graph(
            lambda request: None, checkpointer=saver,  # type: ignore[arg-type]
            generate_planner=planner, persist_planning_result=services.persist,
            record_plan_approval=services.approve,
            materialize_approved_composition=services.materialize,
            enqueue_next_complete_export_job=services.enqueue,
            collect_complete_export_artifact=services.collect,
        )
        publisher = ParentGraphActionPublisher(graph, load_run=loader)
        await publisher.publish(action(run, "start"))
        await publisher.publish(action(run, "start"))
        snapshot = await graph.aget_state({"configurable": {"thread_id": run.thread_id}})
        decision = PlanApprovalDecision(
            decision="approve", actor_id="dispatcher-test",
            approval_assertion="I authorize this exact persisted plan.",
            expected_plan_hash=snapshot.values["plan_hash"],
        )
        loader.run = run.model_copy(update={"status": AIRunStatus.MATERIALIZING})
        await publisher.publish(action(loader.run, "resume", decision))
        await publisher.publish(action(loader.run, "resume", decision))

        assert planner.calls == services.persist_calls == 1
        assert services.materialize_calls == services.enqueue_calls == 1

        cancel_run = run.model_copy(update={
            "run_id": uuid4(), "thread_id": f"cancel-{uuid4().hex}",
            "status": AIRunStatus.QUEUED,
        })
        loader.run = cancel_run
        await publisher.publish(action(cancel_run, "start"))
        loader.run = cancel_run.transition(AIRunStatus.CANCELLED, now=datetime.now(UTC))
        await publisher.publish(action(loader.run, "cancel"))
        cancelled = await graph.aget_state({"configurable": {"thread_id": cancel_run.thread_id}})
        assert cancelled.values["terminal_status"] == "cancelled"
