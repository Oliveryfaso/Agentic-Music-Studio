from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from langgraph.types import Command
from motif_forge.agent.generate import GenerateRequest, initial_generate_state
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.application.ai_runs import (
    CreateAIRun,
    CreateAIRunRequest,
    ReadAIRun,
    RecordAIRunApproval,
)
from motif_forge.application.generation import (
    CollectCompleteExportArtifact,
    EnqueueNextCompleteExportJob,
    MaterializeApprovedComposition,
    PersistPlanningResult,
)
from motif_forge.application.media_jobs import (
    ApplyWorkerEvent,
    EnqueueFollowupMediaJob,
    EnqueueMediaJob,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    ArtifactValidationStatus,
    AudioArtifact,
    ExportBundleArtifact,
    MediaQualityProfile,
    RenderScope,
    WorkerEvent,
)
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.generation import (
    PostgresCompositionMaterializationUnitOfWork,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.worker.outbox import OutboxMessage, ParentGraphActionPublisher
from sqlalchemy import text

from .test_postgres_generate_materialization import _brief, _plan


class RecordingPlanner:
    def __init__(self) -> None:
        self.calls = 0
        self.delegate = StaticCompositionPlanner(_plan())

    async def create_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return await self.delegate.create_plan(*args, **kwargs)

    async def repair_plan(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await self.delegate.repair_plan(*args, **kwargs)


class Harness:
    def __init__(self, dsn: str) -> None:
        self.engine = create_postgres_engine(dsn)
        sessions = create_session_factory(self.engine)
        self.projects = PostgresUnitOfWork(sessions)
        self.ai = PostgresAIRunUnitOfWork(sessions)
        self.media = PostgresMediaJobUnitOfWork(sessions)
        self.materialization = PostgresCompositionMaterializationUnitOfWork(sessions)
        self.planner = RecordingPlanner()
        self.project = None
        self.run = None
        self.arrangement_hash: str | None = None

    async def create(self, case: str) -> None:
        self.project = await CreateProject(self.projects)(
            CreateProjectRequest(
                name=f"S2 combined {case} {uuid4().hex}",
                actor_id="integration-human",
                idempotency_key=f"project-{uuid4().hex}",
            )
        )
        brief = _brief()
        self.run = await CreateAIRun(self.ai)(
            CreateAIRunRequest(
                project_id=self.project.project_id,
                branch_id=self.project.active_branch_id,
                base_revision_id=self.project.root_revision_id,
                thread_id=f"s2-{case}-{uuid4().hex}",
                brief=brief,
                idempotency_key=f"run-{uuid4().hex}",
            )
        )

    def graph(self, saver):  # type: ignore[no-untyped-def]
        enqueue = EnqueueNextCompleteExportJob(
            self.media,
            enqueue_first=EnqueueMediaJob(self.media),
            enqueue_followup=EnqueueFollowupMediaJob(self.media),
        )
        return build_parent_graph(
            lambda request: None,
            checkpointer=saver,  # type: ignore[arg-type]
            generate_planner=self.planner,
            persist_planning_result=PersistPlanningResult(self.ai),
            record_plan_approval=RecordAIRunApproval(self.ai),
            materialize_approved_composition=MaterializeApprovedComposition(self.materialization),
            enqueue_next_complete_export_job=enqueue,
            collect_complete_export_artifact=CollectCompleteExportArtifact(self.media),
        )

    def initial(self) -> dict[str, object]:
        assert self.project is not None and self.run is not None
        brief = _brief()
        return initial_generate_state(
            thread_id=self.run.thread_id,
            request=GenerateRequest(
                run_id=self.run.run_id,
                project_id=self.project.project_id,
                branch_id=self.project.active_branch_id,
                base_revision_id=self.project.root_revision_id,
                brief=brief,
                seed=17,
            ),
        )

    async def finish_job(
        self, state: dict[str, object], *, wrong_lineage: bool = False, failed: bool = False
    ) -> dict[str, object]:
        job_id = UUID(str(state["pending_job_id"]))
        async with self.media() as transaction:
            job = await transaction.get_media_job(job_id)
        assert job is not None and self.project is not None
        event_id = f"task10-{job_id}"
        artifact = None if failed else self._artifact(job, state, wrong_lineage=wrong_lineage)
        outcome = await ApplyWorkerEvent(self.media)(
            WorkerEvent(
                event_id=event_id,
                job_id=job_id,
                event_type="job.failed_terminal" if failed else "job.completed",
                artifact=artifact,
                error_code="RENDER_FAILED" if failed else None,
                occurred_at=datetime.now(UTC),
            )
        )
        return {
            "schema_version": "worker-resume.v1",
            "run_id": str(outcome.run_id),
            "thread_id": str(state["thread_id"]),
            "run_type": "complete_song_export.v1",
            "resume_event_id": event_id,
            "job_id": str(job_id),
            "status": outcome.status.value,
            "artifact_id": str(outcome.artifact_id) if outcome.artifact_id else None,
            "error_code": "RENDER_FAILED" if failed else None,
        }

    def _artifact(self, job, state: dict[str, object], *, wrong_lineage: bool):  # type: ignore[no-untyped-def]
        assert self.project is not None
        cursor = state["export_cursor"]
        assert isinstance(cursor, dict)
        artifact_id, now = uuid4(), datetime.now(UTC)
        revision_id = UUID(str(cursor["revision_id"]))
        if job.output_quality_profile is MediaQualityProfile.EXPORT_BUNDLE_V1:
            return ExportBundleArtifact(
                artifact_id=artifact_id,
                project_id=self.project.project_id,
                source_job_id=job.job_id,
                revision_id=revision_id,
                content_hash=artifact_id.hex * 2,
                byte_size=4096,
                storage_prefix=f"exports/{artifact_id}",
                file_count=13,
                arrangement_hash=str(job.input_payload["arrangement_hash"]),
                engine_version="motif-forge-audio-engine.v1",
                seed=int(cursor["seed"]),
                input_artifact_ids=tuple(UUID(str(item)) for item in cursor["audio_artifact_ids"]),
                created_at=now,
            )
        profile = job.output_quality_profile
        assert profile is not None
        if profile is MediaQualityProfile.DELIVERY_MP3_V1:
            scope, tracks, container, codec = RenderScope.MASTER, (), "mp3", "mp3"
        else:
            scope = RenderScope(str(job.input_payload["render_scope"]))
            tracks = tuple(UUID(str(item)) for item in job.input_payload["render_track_ids"])
            container, codec = "wav", "pcm"
            self.arrangement_hash = str(job.input_payload["arrangement_hash"])
        assert self.arrangement_hash is not None
        return AudioArtifact(
            artifact_id=artifact_id,
            project_id=self.project.project_id,
            revision_id=revision_id,
            arrangement_hash="f" * 64 if wrong_lineage else self.arrangement_hash,
            render_scope=scope,
            render_track_ids=tracks,
            source_job_id=job.job_id,
            content_hash=artifact_id.hex * 2,
            byte_size=4096,
            storage_key=f"audio/{artifact_id}.{container}",
            media_role="generated-export",
            quality_profile=profile,
            container=container,
            codec=codec,
            sample_rate_hz=48_000,
            channels=2,
            duration_seconds=120,
            bitrate_kbps=256 if profile is MediaQualityProfile.DELIVERY_MP3_V1 else None,
            bit_depth=None if profile is MediaQualityProfile.DELIVERY_MP3_V1 else 24,
            encoder="task10-fake-media",
            encoder_version="1",
            lifecycle_class=ArtifactLifecycle.PROTECTED,
            availability=ArtifactAvailability.AVAILABLE,
            validation_status=ArtifactValidationStatus.VALIDATED,
            created_at=now,
        )

    async def counts(self) -> tuple[int, ...]:
        assert self.project is not None and self.run is not None
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT (SELECT count(*) FROM app.composition_plans WHERE run_id=:run),"
                        "(SELECT count(*) FROM app.candidate_snapshots WHERE source_run_id=:run),"
                        "(SELECT count(*) FROM app.project_revisions WHERE source_run_id=:run),"
                        "(SELECT count(*) FROM app.composition_materialization_receipts "
                        "WHERE run_id=:run),"
                        "(SELECT count(*) FROM app.jobs WHERE project_id=:project),"
                        "(SELECT count(*) FROM app.artifacts WHERE project_id=:project),"
                        "(SELECT count(*) FROM app.export_bundle_artifacts "
                        "WHERE project_id=:project)"
                    ),
                    {"run": self.run.run_id, "project": self.project.project_id},
                )
            ).one()
        return tuple(row)

    async def cleanup(self) -> None:
        if self.project is None:
            return
        async with self.engine.begin() as connection:
            await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            statements = (
                "DELETE FROM app.export_bundle_artifacts WHERE project_id=:project",
                "DELETE FROM app.artifacts WHERE project_id=:project",
                "DELETE FROM app.outbox_events WHERE aggregate_id IN "
                "(SELECT id FROM app.jobs WHERE project_id=:project) OR aggregate_id IN "
                "(SELECT id FROM app.runs WHERE project_id=:project)",
                "DELETE FROM app.job_events WHERE job_id IN "
                "(SELECT id FROM app.jobs WHERE project_id=:project)",
                "DELETE FROM app.run_events WHERE run_id IN "
                "(SELECT id FROM app.runs WHERE project_id=:project)",
                "DELETE FROM app.jobs WHERE project_id=:project",
                "DELETE FROM app.runs WHERE project_id=:project",
                "DELETE FROM app.composition_materialization_receipts WHERE run_id IN "
                "(SELECT id FROM app.ai_runs WHERE project_id=:project)",
                "DELETE FROM app.ai_runs WHERE project_id=:project",
                "DELETE FROM app.audit_events WHERE project_id=:project",
                "DELETE FROM app.approvals WHERE project_id=:project",
                "DELETE FROM app.idempotency_records WHERE resource_id=:project OR resource_id IN "
                "(SELECT id FROM app.preview_candidates WHERE project_id=:project) OR "
                "resource_id IN (SELECT id FROM app.project_revisions WHERE project_id=:project)",
                "DELETE FROM app.preview_candidates WHERE project_id=:project",
                "DELETE FROM app.candidate_snapshots WHERE project_id=:project",
                "DELETE FROM app.revision_commands WHERE revision_id IN "
                "(SELECT id FROM app.project_revisions WHERE project_id=:project)",
                "DELETE FROM app.command_batches WHERE project_id=:project",
                "DELETE FROM app.project_branches WHERE project_id=:project",
                "DELETE FROM app.project_revisions WHERE project_id=:project",
                "DELETE FROM app.projects WHERE id=:project",
            )
            for statement in statements:
                await connection.execute(text(statement), {"project": self.project.project_id})
        await self.engine.dispose()


def approval(state: dict[str, object]) -> dict[str, str]:
    return {
        "decision": "approve",
        "actor_id": "s2-integration",
        "approval_assertion": "I approve this exact integrated Plan.",
        "expected_plan_hash": str(state["plan_hash"]),
        "note": "combined checkpoint",
    }


@pytest.mark.asyncio
async def test_complete_generate_survives_restarts_and_duplicate_delivery(
    test_postgres_dsn: str, isolated_postgres_schemas
) -> None:  # type: ignore[no-untyped-def]
    harness = Harness(test_postgres_dsn)
    await harness.create("success")
    assert harness.run is not None
    config = {"configurable": {"thread_id": harness.run.thread_id}}
    start = OutboxMessage(
        event_id=uuid4(),
        topic="graph.start.requested",
        dedupe_key=f"start:{harness.run.run_id}",
        payload={
            "schema_version": "graph-action.v1",
            "action": "start",
            "run_id": str(harness.run.run_id),
            "thread_id": harness.run.thread_id,
            "run_type": "parent.generate.v1",
            "decision": None,
        },
        attempts=1,
    )
    try:
        async with postgres_checkpointer(
            test_postgres_dsn, schema=isolated_postgres_schemas.primary
        ) as saver:
            graph = harness.graph(saver)
            publisher = ParentGraphActionPublisher(graph, load_run=ReadAIRun(harness.ai))
            await publisher.publish(start)
            await publisher.publish(start)
            waiting = (await graph.aget_state(config)).values
        async with postgres_checkpointer(
            test_postgres_dsn, schema=isolated_postgres_schemas.primary
        ) as saver:
            graph = harness.graph(saver)
            state = await graph.ainvoke(Command(resume=approval(waiting)), config)
            master = await harness.finish_job(state)
            state = await graph.ainvoke(Command(resume=master), config)
            counts_after_master = await harness.counts()
            replay = await graph.ainvoke(Command(resume=master), config)
            assert replay["artifact_refs"] == state["artifact_refs"]
            assert await harness.counts() == counts_after_master
            state = replay
        async with postgres_checkpointer(
            test_postgres_dsn, schema=isolated_postgres_schemas.primary
        ) as saver:
            graph = harness.graph(saver)
            for _ in range(6):
                state = await graph.ainvoke(Command(resume=await harness.finish_job(state)), config)
        assert state["terminal_status"] == "succeeded"
        assert harness.planner.calls == 1
        assert await harness.counts() == (1, 1, 1, 1, 7, 6, 1)
    finally:
        await harness.cleanup()


@pytest.mark.asyncio
async def test_cancel_wrong_lineage_and_terminal_failure_preserve_authoritative_facts(
    test_postgres_dsn: str, isolated_postgres_schemas
) -> None:  # type: ignore[no-untyped-def]
    for case in ("cancel", "lineage", "render"):
        harness = Harness(test_postgres_dsn)
        await harness.create(case)
        assert harness.run is not None
        config = {"configurable": {"thread_id": harness.run.thread_id}}
        try:
            async with postgres_checkpointer(
                test_postgres_dsn, schema=isolated_postgres_schemas.primary
            ) as saver:
                graph = harness.graph(saver)
                waiting = await graph.ainvoke(harness.initial(), config)
                if case == "cancel":
                    result = await graph.ainvoke(Command(resume={"action": "cancel"}), config)
                    assert result["terminal_status"] == "cancelled"
                    assert (await harness.counts())[2:5] == (0, 0, 0)
                    continue
                state = await graph.ainvoke(Command(resume=approval(waiting)), config)
                state = await graph.ainvoke(Command(resume=await harness.finish_job(state)), config)
                safe_refs = list(state["artifact_refs"])
                malicious = await harness.finish_job(
                    state, wrong_lineage=case == "lineage", failed=case == "render"
                )
                result = await graph.ainvoke(Command(resume=malicious), config)
                assert result["terminal_status"] == "failed"
                assert result["error_code"] == (
                    "EXPORT_ARTIFACT_LINEAGE_MISMATCH" if case == "lineage" else "RENDER_FAILED"
                )
                assert result["artifact_refs"] == safe_refs
                assert malicious["artifact_id"] not in result["artifact_refs"]
                assert (await harness.counts())[4] == 2
        finally:
            await harness.cleanup()
