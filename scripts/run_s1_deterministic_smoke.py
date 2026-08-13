#!/usr/bin/env python3
"""Persist, render and export the complete deterministic S1 song."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from motif_forge.application.composition import (
    PrepareDeterministicCompositionPreview,
    PrepareDeterministicCompositionPreviewRequest,
)
from motif_forge.application.generation import (
    CollectCompleteExportArtifact,
    CompleteExportCursor,
    EnqueueNextCompleteExportJob,
)
from motif_forge.application.media_jobs import EnqueueFollowupMediaJob, EnqueueMediaJob
from motif_forge.application.previews import (
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.config import Settings
from motif_forge.domain.media_jobs import (
    AudioArtifact,
    ExportBundleArtifact,
    JobStatus,
)
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.worker.execution import execute_media_job

SEED = 20260812


async def _artifact_for_job(uow: PostgresMediaJobUnitOfWork, job_id: UUID) -> AudioArtifact:
    async with uow() as transaction:
        job = await transaction.get_media_job(job_id)
        if job is None or job.result_artifact_id is None:
            raise RuntimeError(f"S1 Job did not produce an Artifact: {job_id}")
        artifact = await transaction.get_audio_artifact(job.result_artifact_id)
    if artifact is None:
        raise RuntimeError(f"S1 Artifact is missing: {job.result_artifact_id}")
    return artifact


async def _bundle_for_job(uow: PostgresMediaJobUnitOfWork, job_id: UUID) -> ExportBundleArtifact:
    async with uow() as transaction:
        job = await transaction.get_media_job(job_id)
        if job is None or job.result_artifact_id is None:
            raise RuntimeError(f"S1 Bundle Job did not produce an Artifact: {job_id}")
        artifact = await transaction.get_export_bundle_artifact(job.result_artifact_id)
    if artifact is None:
        raise RuntimeError(f"S1 Bundle Artifact is missing: {job.result_artifact_id}")
    return artifact


async def _execute_job(*, job_id: UUID, settings: Settings) -> None:
    if os.environ.get("MOTIF_FORGE_S1_USE_QUEUE") == "1":
        await _wait_for_queued_job(job_id=job_id, settings=settings)
        return
    result = await execute_media_job(job_id, settings=settings, worker_id="s1-smoke-worker")
    if result.status != "succeeded" or result.artifact_id is None:
        raise RuntimeError(
            f"S1 Job failed: job_id={job_id} status={result.status} error={result.error_code}"
        )


async def _wait_for_queued_job(*, job_id: UUID, settings: Settings) -> None:
    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required")
    engine = create_postgres_engine(settings.postgres_dsn.get_secret_value())
    sessions = create_session_factory(engine)
    uow = PostgresMediaJobUnitOfWork(sessions)
    deadline = asyncio.get_running_loop().time() + 360.0
    try:
        while asyncio.get_running_loop().time() < deadline:
            async with uow() as transaction:
                job = await transaction.get_media_job(job_id)
            if job is None:
                raise RuntimeError(f"S1 queued Job disappeared: {job_id}")
            if job.status is JobStatus.SUCCEEDED:
                if job.result_artifact_id is None:
                    raise RuntimeError(f"S1 queued Job has no Artifact: {job_id}")
                return
            if job.status in {JobStatus.FAILED_TERMINAL, JobStatus.CANCELLED}:
                raise RuntimeError(
                    "S1 queued Job failed: "
                    f"job_id={job_id} status={job.status} error={job.error_code}"
                )
            await asyncio.sleep(0.25)
        raise TimeoutError(f"S1 queued Job timed out: {job_id}")
    finally:
        await engine.dispose()


async def main() -> None:
    artifact_root_value = os.environ.get("MOTIF_FORGE_ARTIFACT_ROOT", "").strip()
    if not artifact_root_value:
        raise RuntimeError("MOTIF_FORGE_ARTIFACT_ROOT is required")
    approval_assertion = os.environ.get("MOTIF_FORGE_S1_APPROVAL_ASSERTION", "").strip()
    approval_actor = os.environ.get("MOTIF_FORGE_S1_APPROVAL_ACTOR", "").strip()
    if len(approval_assertion) < 16 or not approval_actor:
        raise RuntimeError(
            "MOTIF_FORGE_S1_APPROVAL_ASSERTION (16+ chars) and "
            "MOTIF_FORGE_S1_APPROVAL_ACTOR are required"
        )
    settings = Settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required")
    artifact_root = Path(artifact_root_value).resolve()
    if not artifact_root.is_dir():
        raise RuntimeError("ARTIFACT_ROOT_UNAVAILABLE")

    engine = create_postgres_engine(settings.postgres_dsn.get_secret_value())
    sessions = create_session_factory(engine)
    project_uow = PostgresUnitOfWork(sessions)
    media_uow = PostgresMediaJobUnitOfWork(sessions)
    invocation = uuid4().hex
    try:
        project = await CreateProject(project_uow)(
            CreateProjectRequest(
                name=f"S1 deterministic smoke {invocation[:8]}",
                actor_id="system:s1-smoke",
                idempotency_key=f"s1-project-{invocation}",
            )
        )
        preview = await PrepareDeterministicCompositionPreview(project_uow)(
            PrepareDeterministicCompositionPreviewRequest(
                project_id=project.project_id,
                branch_id=project.active_branch_id,
                base_revision_id=project.root_revision_id,
                seed=SEED,
                actor_id="system:s1-composer",
                idempotency_key=f"s1-preview-{invocation}",
            )
        )
        decision = await DecidePreview(project_uow)(
            DecidePreviewRequest(
                preview_id=preview.preview_id,
                decision=PreviewDecision.APPROVE,
                actor_id=approval_actor,
                approval_assertion=approval_assertion,
                idempotency_key=f"s1-approve-{invocation}",
            )
        )
        if decision.revision_id is None:
            raise RuntimeError("S1 approval did not materialize a Revision")
        revision_id = decision.revision_id
        async with project_uow() as transaction:
            revision = await transaction.get_revision(revision_id)
        if revision is None:
            raise RuntimeError("S1 approved Revision is unavailable")
        thread_id = f"s1-smoke-{invocation}"
        enqueue_export = EnqueueNextCompleteExportJob(
            media_uow,
            enqueue_first=EnqueueMediaJob(media_uow),
            enqueue_followup=EnqueueFollowupMediaJob(media_uow),
        )
        collect_export = CollectCompleteExportArtifact(media_uow)
        cursor = CompleteExportCursor(
            project_id=project.project_id,
            revision_id=revision_id,
            thread_id=thread_id,
            seed=SEED,
        )
        while cursor.pending_steps:
            cursor = await enqueue_export(cursor)
            assert cursor.pending_job_id is not None
            await _execute_job(job_id=cursor.pending_job_id, settings=settings)
            cursor = await collect_export(cursor)
        if cursor.media_run_id is None or cursor.bundle_artifact_id is None:
            raise RuntimeError("S1 shared export orchestration did not complete")
        master = await _artifact_for_job(media_uow, cursor.completed_job_ids[0])
        if master.duration_seconds is None:
            raise RuntimeError("S1 Master duration metadata is missing")
        bundle = await _bundle_for_job(media_uow, cursor.completed_job_ids[-1])
        manifest_path = artifact_root / bundle.storage_prefix / "export-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if len(manifest["files"]) != 12:
            raise RuntimeError("S1 Export Manifest is incomplete")
        print(
            json.dumps(
                {
                    "project_id": str(project.project_id),
                    "revision_id": str(revision_id),
                    "run_id": str(cursor.media_run_id),
                    "duration_seconds": master.duration_seconds,
                    "master_bytes": master.byte_size,
                    "stem_count": 4,
                    "bundle": bundle.model_dump(mode="json"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"S1 deterministic smoke failed: {exc}", file=sys.stderr)
        raise
