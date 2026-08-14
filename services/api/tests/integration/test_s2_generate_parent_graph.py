from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from langgraph.types import Command
from motif_forge.agent.generate import GenerateRequest, initial_generate_state
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.generation import (
    CompleteExportCursor,
    MaterializeApprovedCompositionResult,
    PersistPlanningResultResult,
)
from motif_forge.domain.ai_runs import AIRun, AIRunApproval, composition_plan_content_hash
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.worker.outbox import OutboxMessage, ParentGraphActionPublisher

from .sample_data import valid_brief_payload, valid_plan_payload


class RecordingPlanner:
    def __init__(self) -> None:
        self.calls = 0
        self.delegate = StaticCompositionPlanner(CompositionPlan.model_validate_json(
            json.dumps(valid_plan_payload()), strict=True
        ))

    async def create_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return await self.delegate.create_plan(*args, **kwargs)

    async def repair_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await self.delegate.repair_plan(*args, **kwargs)


class Facts:
    def __init__(self) -> None:
        self.plan_id, self.revision_id, self.media_run_id = uuid4(), uuid4(), uuid4()
        self.job_ids = [uuid4() for _ in range(7)]
        self.artifact_ids = [uuid4() for _ in range(7)]
        self.plan_count = self.candidate_count = self.revision_count = 0
        self.enqueue_count = self.collect_count = 0
        self.events: list[str] = []

    async def persist(self, request):  # type: ignore[no-untyped-def]
        self.plan_count += 1
        self.events.append("plan.persisted")
        plan = CompositionPlan.model_validate_json(
            json.dumps(request.planning_result["plan"]), strict=True
        )
        return PersistPlanningResultResult(
            run_id=request.run_id, plan_id=self.plan_id,
            plan_hash=composition_plan_content_hash(plan),
            interrupt_ref="s2-combined-approval-interrupt", run_version=1,
        )

    async def approve(self, **kwargs):  # type: ignore[no-untyped-def]
        return AIRunApproval(
            approval_id=uuid4(), run_id=kwargs["run_id"], assertion_hash="a" * 64,
            decision=kwargs["decision"], actor_id=kwargs["actor_id"],
            expected_plan_content_hash=kwargs["expected_plan_content_hash"],
            interrupt_ref=kwargs["interrupt_ref"], decided_at=datetime.now(UTC),
        )

    async def materialize(self, request):  # type: ignore[no-untyped-def]
        self.candidate_count += 1
        self.revision_count += 1
        self.events.extend(("candidate.created", "revision.materialized"))
        return MaterializeApprovedCompositionResult(
            status="approved", plan_id=request.plan_id, candidate_snapshot_id=uuid4(),
            preview_id=uuid4(), revision_id=self.revision_id, receipt_id=uuid4(),
        )

    async def enqueue(self, cursor: CompleteExportCursor) -> CompleteExportCursor:
        if cursor.pending_job_id is not None or not cursor.pending_steps:
            return cursor
        index = len(cursor.completed_steps)
        self.enqueue_count += 1
        self.events.append(f"job.{index}.enqueued")
        return cursor.model_copy(update={
            "media_run_id": self.media_run_id, "pending_job_id": self.job_ids[index],
            "pending_idempotency_key": f"s2-export-{index}",
        })

    async def collect(
        self, cursor: CompleteExportCursor, *, completed_job_id: UUID | None = None
    ) -> CompleteExportCursor:
        assert completed_job_id == cursor.pending_job_id
        index = len(cursor.completed_steps)
        self.collect_count += 1
        self.events.append(f"job.{index}.completed")
        update: dict[str, object] = {
            "pending_job_id": None, "pending_idempotency_key": None,
            "completed_steps": (*cursor.completed_steps, cursor.pending_steps[0]),
            "completed_job_ids": (*cursor.completed_job_ids, completed_job_id),
        }
        if index < 6:
            update["audio_artifact_ids"] = (*cursor.audio_artifact_ids, self.artifact_ids[index])
        else:
            update["bundle_artifact_id"] = self.artifact_ids[index]
        return cursor.model_copy(update=update)


def request(run_id: UUID, thread_id: str) -> GenerateRequest:
    return GenerateRequest(
        run_id=run_id, project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
        brief=CompositionBrief.model_validate_json(
            json.dumps(valid_brief_payload()), strict=True
        ), seed=17,
    )


def approval(state: dict[str, object]) -> dict[str, str]:
    return {
        "decision": "approve", "actor_id": "s2-integration",
        "approval_assertion": "I approve this exact integrated Plan.",
        "expected_plan_hash": str(state["plan_hash"]), "note": "combined checkpoint",
    }


def completion(state: dict[str, object], *, status: str = "succeeded") -> dict[str, object]:
    return {
        "schema_version": "worker-resume.v1", "run_id": state["media_run_id"],
        "thread_id": state["thread_id"], "run_type": "complete_song_export.v1",
        "resume_event_id": f"complete-{state['pending_job_id']}",
        "job_id": state["pending_job_id"], "status": status,
        "artifact_id": uuid4() if status == "succeeded" else None,
        "error_code": None if status == "succeeded" else "RENDER_FAILED",
    }


def graph(saver, planner: RecordingPlanner, facts: Facts):  # type: ignore[no-untyped-def]
    return build_parent_graph(
        lambda request: None, checkpointer=saver,  # type: ignore[arg-type]
        generate_planner=planner, persist_planning_result=facts.persist,
        record_plan_approval=facts.approve,
        materialize_approved_composition=facts.materialize,
        enqueue_next_complete_export_job=facts.enqueue,
        collect_complete_export_artifact=facts.collect,
    )


@pytest.mark.asyncio
async def test_complete_generate_survives_two_restarts_and_duplicate_delivery(
    test_postgres_dsn: str, isolated_postgres_schemas,
) -> None:  # type: ignore[no-untyped-def]
    thread_id, run_id = f"s2-complete-{uuid4().hex}", uuid4()
    config = {"configurable": {"thread_id": thread_id}}
    planner, facts = RecordingPlanner(), Facts()
    brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)
    run = AIRun(
        run_id=run_id, project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
        thread_id=thread_id, brief=brief.model_dump(mode="json"),
    )

    async def load_run(requested_run_id: UUID) -> AIRun:
        assert requested_run_id == run.run_id
        return run

    start = OutboxMessage(
        event_id=uuid4(), topic="graph.start.requested", dedupe_key=f"start:{run_id}",
        payload={
            "schema_version": "graph-action.v1", "action": "start",
            "run_id": str(run_id), "thread_id": thread_id,
            "run_type": "parent.generate.v1", "decision": None,
        }, attempts=1,
    )
    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as saver:
        first = graph(saver, planner, facts)
        publisher = ParentGraphActionPublisher(first, load_run=load_run)
        await publisher.publish(start)
        await publisher.publish(start)
        waiting = (await first.aget_state(config)).values
        assert waiting["phase"] == "waiting_plan_approval"

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as saver:
        resumed = graph(saver, planner, facts)
        state = await resumed.ainvoke(Command(resume=approval(waiting)), config)
        master = completion(state)
        state = await resumed.ainvoke(Command(resume=master), config)
        duplicate = await resumed.ainvoke(Command(resume=master), config)
        assert duplicate["artifact_refs"] == state["artifact_refs"]
        assert facts.collect_count == 1
        state = duplicate

    async with postgres_checkpointer(
        test_postgres_dsn, schema=isolated_postgres_schemas.primary
    ) as saver:
        reopened = graph(saver, planner, facts)
        for _ in range(6):
            state = await reopened.ainvoke(Command(resume=completion(state)), config)

    assert state["terminal_status"] == "succeeded"
    assert planner.calls == facts.plan_count == facts.candidate_count == facts.revision_count == 1
    assert facts.enqueue_count == facts.collect_count == 7
    assert len(state["artifact_refs"]) == 7
    assert len(state["export_cursor"]["audio_artifact_ids"]) == 6
    assert state["export_cursor"]["bundle_artifact_id"] is not None
    assert facts.events[:3] == [
        "plan.persisted", "candidate.created", "revision.materialized"
    ]
    assert facts.events[3:] == [
        item for index in range(7)
        for item in (f"job.{index}.enqueued", f"job.{index}.completed")
    ]


@pytest.mark.asyncio
async def test_cancel_lineage_mismatch_and_terminal_render_failure_are_finite(
    test_postgres_dsn: str, isolated_postgres_schemas,
) -> None:  # type: ignore[no-untyped-def]
    for case in ("cancel", "lineage", "render"):
        thread_id = f"s2-{case}-{uuid4().hex}"
        config = {"configurable": {"thread_id": thread_id}}
        planner, facts = RecordingPlanner(), Facts()
        async with postgres_checkpointer(
            test_postgres_dsn, schema=isolated_postgres_schemas.primary
        ) as saver:
            current = graph(saver, planner, facts)
            waiting = await current.ainvoke(
                initial_generate_state(
                    thread_id=thread_id, request=request(uuid4(), thread_id)
                ), config,
            )
            if case == "cancel":
                result = await current.ainvoke(Command(resume={"action": "cancel"}), config)
                assert result["terminal_status"] == "cancelled"
                assert facts.revision_count == facts.enqueue_count == 0
                continue
            state = await current.ainvoke(Command(resume=approval(waiting)), config)
            payload = completion(
                state, status="failed_terminal" if case == "render" else "succeeded"
            )
            if case == "lineage":
                payload["run_id"] = str(uuid4())
            result = await current.ainvoke(Command(resume=payload), config)
            assert result["terminal_status"] == "failed"
            assert result["error_code"] == (
                "WORKER_RESUME_MISMATCH" if case == "lineage" else "RENDER_FAILED"
            )
            assert facts.enqueue_count == 1
