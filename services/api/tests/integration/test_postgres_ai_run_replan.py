from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, PlanAdjustment
from motif_forge.application.ai_runs import (
    CreateAIRun,
    CreateAIRunRequest,
    ReadAIRun,
    ReadAIRunProjection,
    RecordAIRunApproval,
    ReplanAIRun,
    ReplanAIRunRequest,
)
from motif_forge.application.errors import ApplicationError
from motif_forge.application.generation import (
    PersistPlanningResult,
    PersistPlanningResultRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.tables import (
    AIRunActionIdempotencyRow,
    AIRunRow,
    CompositionPlanRow,
    MediaJobRow,
    OutboxEventRow,
    RevisionRow,
)
from motif_forge.worker.outbox import (
    OutboxMessage,
    ParentGraphActionPublisher,
)
from sqlalchemy import func, select, text

from .sample_data import valid_brief_payload, valid_plan_payload


def _upgrade(dsn: str) -> None:
    root = Path(__file__).resolve().parents[4]
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(root / "alembic.ini"), "head")


def _adjustment(*, bpm: int = 90) -> PlanAdjustment:
    return PlanAdjustment.model_validate_json(json.dumps({
        "schema_version": "plan-adjustment.v1",
        "target_bpm": bpm,
        "target_key": "E minor",
        "sections": [
            {"name": "Arrival", "bars": 8, "energy": 0.25},
            {"name": "Motion", "bars": 24, "energy": 0.7},
        ],
        "instrumentation": [
            {"name": "Glass Pad", "role": "harmony"},
            {"name": "Muted Pulse", "role": "rhythm"},
        ],
        "note": "Keep the transition gradual.",
    }), strict=True)


@pytest.mark.asyncio
async def test_postgres_replan_is_immutable_idempotent_and_approval_gated(
    test_postgres_dsn: str, isolated_postgres_schemas,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(CreateProjectRequest(
        name=f"S3 replan {uuid4().hex}", actor_id="s3-test",
        idempotency_key=f"s3-project-{uuid4().hex}",
    ))
    uow = PostgresAIRunUnitOfWork(sessions)
    parent = await CreateAIRun(uow)(CreateAIRunRequest(
        project_id=project.project_id, branch_id=project.active_branch_id,
        base_revision_id=project.root_revision_id, thread_id=f"s3-parent-{uuid4().hex}",
        brief=CompositionBrief.model_validate_json(
            json.dumps(valid_brief_payload()), strict=True
        ), idempotency_key=f"s3-parent-{uuid4().hex}", max_model_requests=1,
    ))
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    pending = await PersistPlanningResult(uow)(PersistPlanningResultRequest(
        run_id=parent.run_id, expected_run_version=0,
        planning_result={
            "phase": "planning_complete",
            "plan": plan.model_dump(mode="json"),
            "provider_metadata": {
                "provider": "deterministic",
                "model": "s3-static",
                "prompt_version": "s3-test.v1",
                "schema_version": "composition-plan.v1",
            },
            "usage": {}, "counters": {"model_requests": 0},
        },
    ))
    try:
        async with sessions() as session:
            parent_before = (
                await session.execute(select(AIRunRow).where(AIRunRow.id == parent.run_id))
            ).scalar_one()
            plan_before = (
                await session.execute(
                    select(CompositionPlanRow).where(CompositionPlanRow.id == pending.plan_id)
                )
            ).scalar_one()
            parent_snapshot = (
                parent_before.status, parent_before.version, parent_before.brief,
                parent_before.pending_plan_id, parent_before.pending_plan_content_hash,
            )
            plan_snapshot = (
                plan_before.plan, plan_before.content_hash, plan_before.hash_version,
                plan_before.provider, plan_before.model,
            )

        request = ReplanAIRunRequest(
            run_id=parent.run_id, expected_version=pending.run_version,
            expected_plan_hash=pending.plan_hash, adjustment=_adjustment(),
            idempotency_key="s3-replan-key",
        )
        child = await ReplanAIRun(uow)(request)
        replay = await ReplanAIRun(uow)(request)

        assert replay.run_id == child.run_id
        assert child.parent_run_id == parent.run_id
        assert child.project_id == parent.project_id
        assert child.branch_id == parent.branch_id
        assert child.base_revision_id == parent.base_revision_id
        assert child.max_model_requests == parent.max_model_requests == 1
        child_brief = CompositionBrief.model_validate_json(
            json.dumps(child.brief), strict=True
        )
        assert child_brief.target_bpm == 90
        assert child_brief.preferred_instruments == ("Glass Pad", "Muted Pulse")

        with pytest.raises(ApplicationError, match="IDEMPOTENCY_KEY_REUSED"):
            await ReplanAIRun(uow)(request.model_copy(update={
                "adjustment": _adjustment(bpm=91)
            }))
        with pytest.raises(ApplicationError, match="AI_RUN_REPLAN_STATE_CONFLICT"):
            await ReplanAIRun(uow)(request.model_copy(update={
                "expected_version": pending.run_version + 1,
                "idempotency_key": "s3-stale-version",
            }))
        with pytest.raises(ApplicationError, match="AI_RUN_REPLAN_STATE_CONFLICT"):
            await ReplanAIRun(uow)(request.model_copy(update={
                "expected_plan_hash": "f" * 64,
                "idempotency_key": "s3-stale-hash",
            }))

        async with sessions() as session:
            parent_after = (
                await session.execute(select(AIRunRow).where(AIRunRow.id == parent.run_id))
            ).scalar_one()
            plan_after = (
                await session.execute(
                    select(CompositionPlanRow).where(CompositionPlanRow.id == pending.plan_id)
                )
            ).scalar_one()
            child_count = await session.scalar(
                select(func.count()).select_from(AIRunRow).where(
                    AIRunRow.parent_run_id == parent.run_id
                )
            )
            action_count = await session.scalar(
                select(func.count()).select_from(AIRunActionIdempotencyRow).where(
                    AIRunActionIdempotencyRow.parent_run_id == parent.run_id,
                    AIRunActionIdempotencyRow.action == "replan",
                )
            )
            outbox_count = await session.scalar(
                select(func.count()).select_from(OutboxEventRow).where(
                    OutboxEventRow.aggregate_id == child.run_id,
                    OutboxEventRow.topic == "graph.start.requested",
                )
            )
            revision_count = await session.scalar(
                select(func.count()).select_from(RevisionRow).where(
                    RevisionRow.source_run_id == child.run_id
                )
            )
            job_count = await session.scalar(
                select(func.count()).select_from(MediaJobRow).where(
                    MediaJobRow.project_id == project.project_id
                )
            )
        assert (
            parent_after.status, parent_after.version, parent_after.brief,
            parent_after.pending_plan_id, parent_after.pending_plan_content_hash,
        ) == parent_snapshot
        assert (
            plan_after.plan, plan_after.content_hash, plan_after.hash_version,
            plan_after.provider, plan_after.model,
        ) == plan_snapshot
        assert child_count == action_count == outbox_count == 1
        assert revision_count == job_count == 0

        async with sessions() as session:
            child_outbox = (
                await session.execute(
                    select(OutboxEventRow).where(
                        OutboxEventRow.aggregate_id == child.run_id,
                        OutboxEventRow.topic == "graph.start.requested",
                    )
                )
            ).scalar_one()
        message = OutboxMessage(
            event_id=child_outbox.id,
            topic=child_outbox.topic,
            dedupe_key=child_outbox.dedupe_key,
            payload=dict(child_outbox.payload),
            attempts=child_outbox.attempts,
        )

        async def unexpected(*args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            raise AssertionError("approval-gated child must not materialize or export")

        async with postgres_checkpointer(
            test_postgres_dsn, schema=isolated_postgres_schemas.primary
        ) as saver:
            graph = build_parent_graph(
                unexpected,
                checkpointer=saver,
                generate_planner=StaticCompositionPlanner(plan),
                persist_planning_result=PersistPlanningResult(uow),
                record_plan_approval=RecordAIRunApproval(uow),
                materialize_approved_composition=unexpected,
                enqueue_next_complete_export_job=unexpected,
                collect_complete_export_artifact=unexpected,
            )
            publisher = ParentGraphActionPublisher(graph, load_run=ReadAIRun(uow))
            assert message.payload["run_id"] == str(child.run_id)
            await publisher.publish(message)
            await publisher.publish(message)

        waiting_child = await ReadAIRun(uow)(child.run_id)
        child_projection = await ReadAIRunProjection(uow)(child.run_id)
        assert waiting_child.status.value == "waiting_approval"
        assert child_projection.plan is not None
        assert child_projection.plan.plan == plan
        assert child_projection.progress is not None
        assert child_projection.progress.phase == "waiting_approval"
        assert child_projection.progress.completed_export_steps == ()
        assert child_projection.progress.total_export_steps == 7
        assert child_projection.progress.latest_event_sequence > 0
        async with sessions() as session:
            child_plan_count = await session.scalar(
                select(func.count()).select_from(CompositionPlanRow).where(
                    CompositionPlanRow.run_id == child.run_id
                )
            )
            child_revision_count = await session.scalar(
                select(func.count()).select_from(RevisionRow).where(
                    RevisionRow.source_run_id == child.run_id
                )
            )
            child_job_count = await session.scalar(
                select(func.count()).select_from(MediaJobRow).where(
                    MediaJobRow.project_id == project.project_id
                )
            )
        assert child_plan_count == 1
        assert child_revision_count == child_job_count == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(
                "DELETE FROM app.outbox_events WHERE aggregate_id IN "
                "(SELECT id FROM app.ai_runs WHERE project_id=:project_id)"
            ), {"project_id": project.project_id})
            await connection.execute(text(
                "DELETE FROM app.ai_run_action_idempotency WHERE parent_run_id IN "
                "(SELECT id FROM app.ai_runs WHERE project_id=:project_id)"
            ), {"project_id": project.project_id})
            await connection.execute(
                text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.projects WHERE id=:project_id"),
                {"project_id": project.project_id},
            )
        await engine.dispose()
