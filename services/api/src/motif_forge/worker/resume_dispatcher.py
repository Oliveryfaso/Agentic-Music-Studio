"""Dedicated Parent Graph Resume Outbox dispatcher."""

from __future__ import annotations

import asyncio
import os
import socket

from motif_forge.agent.parent_graph import build_parent_graph
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
from motif_forge.config import get_settings
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork
from motif_forge.worker.outbox import (
    GRAPH_RESUME_TOPICS,
    ParentGraphResumePublisher,
    PostgresOutboxStore,
    dispatch_once,
)


async def run_resume_dispatcher() -> None:
    settings = get_settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("resume dispatcher requires PostgreSQL configuration")
    dsn = settings.postgres_dsn.get_secret_value()
    engine = create_postgres_engine(dsn)
    session_factory = create_session_factory(engine)
    store = PostgresOutboxStore(
        session_factory,
        topics=GRAPH_RESUME_TOPICS,
        run_type_prefix="parent.",
    )
    owner = f"resume:{socket.gethostname()}:{os.getpid()}"
    try:
        async with postgres_checkpointer(dsn) as saver:
            storage_uow = PostgresStorageUnitOfWork(session_factory)
            graph = build_parent_graph(
                EnqueueMediaJob(PostgresMediaJobUnitOfWork(session_factory)),
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
                    load_facts=PostgresStorageFactsLoader(storage_uow),
                    collector=LocalArtifactCollector(
                        storage_uow, artifact_root=settings.artifact_root
                    ),
                    record_event=PersistentStorageEventRecorder(storage_uow),
                    global_quota_bytes=settings.artifact_global_quota_bytes,
                    project_quota_bytes=settings.artifact_project_quota_bytes,
                    temp_quota_bytes=settings.temp_quota_bytes,
                    minimum_free_bytes=settings.storage_min_free_bytes,
                ),
            )
            publisher = ParentGraphResumePublisher(graph)
            while True:
                delivered = await dispatch_once(
                    store,
                    publisher,
                    owner=owner,
                    batch_size=settings.outbox_batch_size,
                    lease_seconds=settings.outbox_lease_seconds,
                )
                if delivered == 0:
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
