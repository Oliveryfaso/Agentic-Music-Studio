"""Representative real PostgreSQL/checkpoint boundary for S5 candidate selection."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langgraph.types import Command
from motif_forge.agent.critic import DeterministicEvidenceCritic
from motif_forge.agent.generate import GenerateRequest, initial_generate_state
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.application.candidate_previews import CandidatePreviewCursor
from motif_forge.application.candidate_repair import (
    ApplyBoundedCandidateRepair,
    EvaluateCandidatePair,
    MeasureCandidateEvidence,
)
from motif_forge.application.generation import (
    CompleteExportCursor,
    PersistPlanningResultResult,
)
from motif_forge.application.generation_candidates import (
    CreateCandidateSelectionPreview,
    CreateCompositionCandidate,
    MaterializeSelectedCompositionCandidate,
)
from motif_forge.application.media_jobs import EnqueueMediaJobRequest, EnqueueMediaJobResult
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.infrastructure.persistence.generation import (
    PostgresCompositionMaterializationUnitOfWork,
)
from motif_forge.worker.outbox import OutboxMessage, ParentGraphResumePublisher
from sqlalchemy import text

from .test_postgres_generate_materialization import (
    _approved_materialization_fixture,
    _brief,
    _delete_exact_project,
    _plan,
)


class _NoLegacyEnqueue:
    async def __call__(self, request: EnqueueMediaJobRequest) -> EnqueueMediaJobResult:
        del request
        raise AssertionError("legacy enqueue must not own S5 candidate previews")


class _PersistExistingPlan:
    def __init__(self, approved) -> None:  # type: ignore[no-untyped-def]
        self._approved = approved

    async def __call__(self, request):  # type: ignore[no-untyped-def]
        del request
        return PersistPlanningResultResult(
            run_id=self._approved.run_id,
            plan_id=self._approved.plan_id,
            plan_hash=self._approved.expected_plan_hash,
            interrupt_ref="s5-existing-plan",
            run_version=1,
        )


class _ExistingApproval:
    async def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return SimpleNamespace()


class _PreviewJobs:
    def __init__(self) -> None:
        self.runs: dict[UUID, UUID] = {}
        self.artifacts: dict[UUID, UUID] = {}

    async def enqueue(self, request):  # type: ignore[no-untyped-def]
        job_id, run_id = uuid4(), uuid4()
        self.runs[job_id] = run_id
        self.artifacts[job_id] = uuid4()
        return CandidatePreviewCursor(
            project_id=request.project_id,
            candidate_snapshot_id=request.candidate_snapshot_id,
            candidate_content_hash=request.expected_candidate_content_hash,
            media_run_id=run_id,
            job_id=job_id,
        )

    async def collect(self, cursor, completed_job_id):  # type: ignore[no-untyped-def]
        return cursor.model_copy(
            update={"preview_artifact_id": self.artifacts[completed_job_id]}
        )


class _ExportBoundary:
    def __init__(self) -> None:
        self.run_id = uuid4()

    async def enqueue(self, cursor: CompleteExportCursor) -> CompleteExportCursor:
        if cursor.pending_job_id is not None:
            return cursor
        return cursor.model_copy(
            update={
                "media_run_id": self.run_id,
                "pending_job_id": uuid4(),
                "pending_idempotency_key": "s5-export-step",
            }
        )

    async def collect(self, cursor, *, completed_job_id=None):  # type: ignore[no-untyped-def]
        del completed_job_id
        return cursor


def _worker_resume(state: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "worker-resume.v1",
        "run_id": str(state["media_run_id"]),
        "thread_id": str(state["thread_id"]),
        "run_type": "parent.candidate_preview.v1",
        "resume_event_id": f"event-{state['pending_job_id']}",
        "job_id": str(state["pending_job_id"]),
        "status": "succeeded",
        "artifact_id": str(uuid4()),
        "error_code": None,
    }


@pytest.mark.asyncio
async def test_s5_checkpoint_restart_materializes_only_selected_candidate(
    test_postgres_dsn: str,
) -> None:
    engine, sessions, _, _, approved = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    compositions = PostgresCompositionMaterializationUnitOfWork(sessions)
    preview_jobs = _PreviewJobs()
    exports = _ExportBoundary()
    config = {"configurable": {"thread_id": f"s5-checkpoint-{uuid4().hex}"}}

    def build(saver):  # type: ignore[no-untyped-def]
        return build_parent_graph(
            _NoLegacyEnqueue(),
            checkpointer=saver,
            generate_planner=StaticCompositionPlanner(_plan()),
            persist_planning_result=_PersistExistingPlan(approved),
            record_plan_approval=_ExistingApproval(),
            materialize_approved_composition=SimpleNamespace(),
            enqueue_next_complete_export_job=exports.enqueue,
            collect_complete_export_artifact=exports.collect,
            create_composition_candidate=CreateCompositionCandidate(compositions),
            enqueue_candidate_preview=preview_jobs.enqueue,
            collect_candidate_preview=preview_jobs.collect,
            evidence_critic=DeterministicEvidenceCritic(),
            create_candidate_selection_preview=CreateCandidateSelectionPreview(compositions),
            materialize_selected_candidate=MaterializeSelectedCompositionCandidate(
                compositions
            ),
            measure_candidate_evidence=MeasureCandidateEvidence(compositions),
            apply_candidate_repair=ApplyBoundedCandidateRepair(compositions),
            candidate_quality_gate=EvaluateCandidatePair(compositions),
        )

    try:
        async with postgres_checkpointer(test_postgres_dsn) as saver:
            graph = build(saver)
            waiting_plan = await graph.ainvoke(
                initial_generate_state(
                    thread_id=config["configurable"]["thread_id"],
                    request=GenerateRequest(
                        run_id=approved.run_id,
                        project_id=approved.project_id,
                        branch_id=approved.branch_id,
                        base_revision_id=approved.base_revision_id,
                        brief=_brief(),
                        seed=0,
                    ),
                ),
                config,
            )
            assert waiting_plan["phase"] == "waiting_plan_approval"
            state = await graph.ainvoke(
                Command(
                    resume={
                        "decision": "approve",
                        "actor_id": approved.actor_id,
                        "approval_assertion": approved.approval_assertion,
                        "expected_plan_hash": approved.expected_plan_hash,
                    }
                ),
                config,
            )
            assert state["phase"] == "rendering_candidate_previews"

            # The dispatcher must rebuild the same S5 topology for every Worker wake.
            publisher = ParentGraphResumePublisher(
                graph,
                graph_for_resume=lambda payload: build(saver),
            )

            async def resume_worker(current: dict[str, object]) -> dict[str, object]:
                payload = _worker_resume(current)
                await publisher.publish(
                    OutboxMessage(
                        event_id=uuid4(),
                        topic="graph.resume.requested",
                        dedupe_key=str(payload["resume_event_id"]),
                        payload=payload,
                        attempts=1,
                    )
                )
                return dict((await graph.aget_state(config)).values)

            state = await resume_worker(state)
            state = await resume_worker(state)
            if state["phase"] == "rendering_candidate_previews":
                state = await resume_worker(state)
            assert state["phase"] == "waiting_candidate_selection"
            selected = state["candidate_working"][1]
            state = await graph.ainvoke(
                Command(
                    resume={
                        "decision": "select",
                        "actor_id": approved.actor_id,
                        "selection_assertion": (
                            "I compared both persisted candidate previews and select B."
                        ),
                        "selected_preview_id": selected["selection_preview_id"],
                        "expected_candidate_id": selected["candidate_id"],
                        "expected_candidate_content_hash": selected[
                            "candidate_content_hash"
                        ],
                    }
                ),
                config,
            )
            assert state["phase"] == "waiting_generate_worker"

        async with engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM app.candidate_snapshots "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.preview_candidates "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.project_revisions "
                        " WHERE source_run_id=:run_id), "
                        "(SELECT count(*) FROM app.composition_materialization_receipts "
                        " WHERE run_id=:run_id)"
                    ),
                    {"run_id": approved.run_id},
                )
            ).one()
        assert tuple(counts) == (3, 2, 1, 1)
    finally:
        await _delete_exact_project(engine, approved.project_id, approved.run_id)
        await engine.dispose()
