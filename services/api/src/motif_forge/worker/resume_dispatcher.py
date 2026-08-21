"""Dedicated Parent Graph Resume Outbox dispatcher."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Mapping
from typing import Any, cast

from motif_forge.agent.critic import (
    DeepSeekEvidenceCritic,
    DeterministicEvidenceCritic,
    EvidenceCritic,
)
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import (
    CompositionPlanner,
    PersistentProviderBudgetLedger,
    PlannerError,
    PlannerResponse,
)
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.application.ai_runs import (
    ReadAIRun,
    RecordAIRunApproval,
    RecordAIRunGraphProgress,
)
from motif_forge.application.generation import (
    CollectCompleteExportArtifact,
    EnqueueNextCompleteExportJob,
    MaterializeApprovedComposition,
    PersistPlanningResult,
)
from motif_forge.application.imports import LoadImportAnalysisContext, MaterializeImport
from motif_forge.application.media_jobs import (
    EnqueueFollowupMediaJob,
    EnqueueMediaJob,
    LoadArtifactRehydration,
    StartArtifactRehydration,
)
from motif_forge.application.storage import (
    LocalArtifactCollector,
    LocalStorageRootInspector,
    PersistentStorageEventRecorder,
    PostgresStorageFactsLoader,
    RunStoragePressureGate,
)
from motif_forge.config import Settings, get_settings
from motif_forge.domain.ai_runs import AIRun
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
from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork
from motif_forge.providers.deepseek import DeepSeekJsonClient, build_synth_ambient_planner
from motif_forge.worker.outbox import (
    GRAPH_ACTION_TOPICS,
    GRAPH_RESUME_TOPICS,
    ParentGraphActionPublisher,
    ParentGraphResumePublisher,
    PostgresOutboxStore,
    dispatch_once,
)


class MissingDeepSeekPlanner:
    async def create_plan(
        self, brief: CompositionBrief, *, allow_schema_repair: bool = True
    ) -> PlannerResponse:
        del brief, allow_schema_repair
        raise PlannerError(
            "DEEPSEEK_API_KEY_MISSING",
            "DeepSeek is not configured; deterministic planning fallback is required.",
            retryable=False,
            suggested_route="fallback",
        )

    async def repair_plan(
        self,
        brief: CompositionBrief,
        *,
        invalid_payload: Mapping[str, Any],
        validation_issues: tuple[str, ...],
    ) -> PlannerResponse:
        del brief, invalid_payload, validation_issues
        raise AssertionError("missing-key planner cannot enter schema repair")


def build_generate_planner(
    settings: Settings, run: AIRun, ai_uow: object
) -> CompositionPlanner:
    if not settings.deepseek_configured:
        return MissingDeepSeekPlanner()
    ledger = PersistentProviderBudgetLedger(
        ai_uow,
        run_id=run.run_id,
        max_requests=run.max_model_requests,
        max_total_tokens=run.max_total_tokens,
    )
    return build_synth_ambient_planner(
        settings, run_id=run.run_id, budget_ledger=cast(Any, ledger)
    )


def build_generate_critic(settings: Settings, run: AIRun, ai_uow: object) -> EvidenceCritic:
    if not settings.deepseek_configured:
        return DeterministicEvidenceCritic()
    ledger = PersistentProviderBudgetLedger(
        ai_uow,
        run_id=run.run_id,
        max_requests=run.max_model_requests,
        max_total_tokens=run.max_total_tokens,
    )
    client = DeepSeekJsonClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        connect_timeout_seconds=settings.deepseek_connect_timeout_seconds,
        read_timeout_seconds=settings.deepseek_read_timeout_seconds,
        max_attempts=1,
        run_id=run.run_id,
        budget_ledger=cast(Any, ledger),
    )
    return DeepSeekEvidenceCritic(client)


async def run_resume_dispatcher() -> None:
    settings = get_settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("resume dispatcher requires PostgreSQL configuration")
    dsn = settings.postgres_dsn.get_secret_value()
    engine = create_postgres_engine(dsn)
    session_factory = create_session_factory(engine)
    store = PostgresOutboxStore(
        session_factory,
        topics=GRAPH_ACTION_TOPICS,
        aggregate_type="ai_run",
    )
    owner = f"resume:{socket.gethostname()}:{os.getpid()}"
    try:
        async with postgres_checkpointer(dsn) as saver:
            storage_uow = PostgresStorageUnitOfWork(session_factory)
            media_uow = PostgresMediaJobUnitOfWork(session_factory)
            ai_uow = PostgresAIRunUnitOfWork(session_factory)

            def graph_with(planner: CompositionPlanner) -> object:
                return build_parent_graph(
                EnqueueMediaJob(media_uow),
                checkpointer=saver,
                materialize_import=MaterializeImport(
                    PostgresUnitOfWork(session_factory),
                    PostgresMediaJobUnitOfWork(session_factory),
                ),
                load_import_context=LoadImportAnalysisContext(
                    PostgresUnitOfWork(session_factory),
                    PostgresMediaJobUnitOfWork(session_factory),
                ),
                enqueue_followup_media_job=EnqueueFollowupMediaJob(
                    PostgresMediaJobUnitOfWork(session_factory)
                ),
                enqueue_artifact_rehydration=StartArtifactRehydration(
                    PostgresMediaJobUnitOfWork(session_factory)
                ),
                load_artifact_rehydration=LoadArtifactRehydration(
                    PostgresMediaJobUnitOfWork(session_factory)
                ),
                storage_pressure_gate=RunStoragePressureGate(
                    inspect_root=LocalStorageRootInspector(settings.artifact_root),
                    load_facts=PostgresStorageFactsLoader(
                        storage_uow, temp_root=settings.temp_root
                    ),
                    collector=LocalArtifactCollector(
                        storage_uow, artifact_root=settings.artifact_root
                    ),
                    record_event=PersistentStorageEventRecorder(storage_uow),
                    global_quota_bytes=settings.artifact_global_quota_bytes,
                    project_quota_bytes=settings.artifact_project_quota_bytes,
                    temp_quota_bytes=settings.temp_quota_bytes,
                    minimum_free_bytes=settings.storage_min_free_bytes,
                ),
                generate_planner=planner,
                persist_planning_result=PersistPlanningResult(ai_uow),
                record_plan_approval=RecordAIRunApproval(ai_uow),
                materialize_approved_composition=MaterializeApprovedComposition(
                    PostgresCompositionMaterializationUnitOfWork(session_factory)
                ),
                enqueue_next_complete_export_job=EnqueueNextCompleteExportJob(
                    media_uow,
                    enqueue_first=EnqueueMediaJob(media_uow),
                    enqueue_followup=EnqueueFollowupMediaJob(media_uow),
                ),
                    collect_complete_export_artifact=CollectCompleteExportArtifact(media_uow),
                )

            def graph_for(run: AIRun) -> object:
                return graph_with(build_generate_planner(settings, run, ai_uow))

            record_progress = RecordAIRunGraphProgress(ai_uow)
            publisher = ParentGraphActionPublisher(
                graph_for,
                load_run=ReadAIRun(ai_uow),
                record_progress=record_progress,
            )
            parent_worker_store = PostgresOutboxStore(
                session_factory,
                topics=GRAPH_RESUME_TOPICS,
                run_type_prefix="parent.",
                aggregate_type="run",
            )
            parent_worker_publisher = ParentGraphResumePublisher(
                graph_with(MissingDeepSeekPlanner())
            )
            export_worker_store = PostgresOutboxStore(
                session_factory,
                topics=GRAPH_RESUME_TOPICS,
                run_type_exact="complete_song_export.v1",
                aggregate_type="run",
            )
            export_worker_publisher = ParentGraphResumePublisher(
                graph_with(MissingDeepSeekPlanner()),
                run_type_prefix=None,
                run_type_exact="complete_song_export.v1",
                record_progress=record_progress,
            )
            while True:
                delivered_actions = await dispatch_once(
                    store,
                    publisher,
                    owner=owner,
                    batch_size=settings.outbox_batch_size,
                    lease_seconds=settings.outbox_lease_seconds,
                )
                delivered_parent_workers = await dispatch_once(
                    parent_worker_store,
                    parent_worker_publisher,
                    owner=f"{owner}:parent-worker",
                    batch_size=settings.outbox_batch_size,
                    lease_seconds=settings.outbox_lease_seconds,
                )
                delivered_export_workers = await dispatch_once(
                    export_worker_store,
                    export_worker_publisher,
                    owner=f"{owner}:export-worker",
                    batch_size=settings.outbox_batch_size,
                    lease_seconds=settings.outbox_lease_seconds,
                )
                if (
                    delivered_actions
                    + delivered_parent_workers
                    + delivered_export_workers
                    == 0
                ):
                    await asyncio.sleep(settings.outbox_poll_interval_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_resume_dispatcher())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
