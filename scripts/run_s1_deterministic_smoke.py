#!/usr/bin/env python3
"""Persist, render and export the complete deterministic S1 song."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from motif_forge.application.composition import (
    PrepareDeterministicCompositionPreview,
    PrepareDeterministicCompositionPreviewRequest,
)
from motif_forge.application.media_jobs import (
    EnqueueFollowupMediaJob,
    EnqueueFollowupMediaJobRequest,
    EnqueueMediaJob,
    EnqueueMediaJobRequest,
)
from motif_forge.application.previews import (
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.config import Settings
from motif_forge.domain.media_jobs import (
    AudioArtifact,
    BundleAudioInput,
    CanonicalRenderJobPayload,
    ExportBundleArtifact,
    ExportBundleJobPayload,
    ExportMp3JobPayload,
    JobStatus,
    MediaJobType,
    MediaQualityProfile,
    RenderScope,
)
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.worker.execution import execute_media_job

SEED = 20260812
ENGINE_VERSION: Literal["motif-forge-audio-engine.v1"] = "motif-forge-audio-engine.v1"


async def _artifact_for_job(
    uow: PostgresMediaJobUnitOfWork, job_id: UUID
) -> AudioArtifact:
    async with uow() as transaction:
        job = await transaction.get_media_job(job_id)
        if job is None or job.result_artifact_id is None:
            raise RuntimeError(f"S1 Job did not produce an Artifact: {job_id}")
        artifact = await transaction.get_audio_artifact(job.result_artifact_id)
    if artifact is None:
        raise RuntimeError(f"S1 Artifact is missing: {job.result_artifact_id}")
    return artifact


async def _bundle_for_job(
    uow: PostgresMediaJobUnitOfWork, job_id: UUID
) -> ExportBundleArtifact:
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


def _bundle_input(
    artifact: AudioArtifact, *, filename: str, profile: MediaQualityProfile
) -> BundleAudioInput:
    if artifact.quality_profile is not profile:
        raise RuntimeError(f"S1 Artifact profile mismatch: {artifact.artifact_id}")
    if artifact.revision_id is None or artifact.arrangement_hash is None:
        raise RuntimeError(f"S1 Artifact revision lineage is missing: {artifact.artifact_id}")
    return BundleAudioInput.model_validate(
        {
            "artifact_id": artifact.artifact_id,
            "quality_profile": profile,
            "content_hash": artifact.content_hash,
            "filename": filename,
        }
    )


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
        arrangement = revision.arrangement_ir

        thread_id = f"s1-smoke-{invocation}"
        master_projection = compile_audio_graph(arrangement)
        master_payload = CanonicalRenderJobPayload(
            project_id=project.project_id,
            revision_id=revision_id,
            render_scope=RenderScope.MASTER,
            render_track_ids=(),
            quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            audio_graph=master_projection.graph,
            audio_graph_hash=master_projection.graph_hash,
            arrangement_hash=master_projection.arrangement_hash,
            audio_engine_version=ENGINE_VERSION,
            seed=SEED,
            timeout_seconds=240,
            maximum_output_bytes=64 * 1024 * 1024,
        )
        first = await EnqueueMediaJob(media_uow)(
            EnqueueMediaJobRequest(
                project_id=project.project_id,
                thread_id=thread_id,
                run_type="s1_deterministic_smoke.v1",
                job_type=MediaJobType.RENDER_CANONICAL,
                input_payload=master_payload.model_dump(mode="json"),
                output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
                idempotency_key=f"s1-master-{invocation}",
                deadline_seconds=300,
            )
        )
        await _execute_job(job_id=first.job_id, settings=settings)
        master = await _artifact_for_job(media_uow, first.job_id)

        stem_artifacts: list[AudioArtifact] = []
        trace_refs = [f"run:{first.run_id}", f"job:{first.job_id}"]
        for track in arrangement.tracks:
            projection = compile_audio_graph(arrangement, render_track_ids=(track.track_id,))
            payload = CanonicalRenderJobPayload(
                project_id=project.project_id,
                revision_id=revision_id,
                render_scope=RenderScope.STEM,
                render_track_ids=(track.track_id,),
                quality_profile=MediaQualityProfile.CANONICAL_STEM_V1,
                audio_graph=projection.graph,
                audio_graph_hash=projection.graph_hash,
                arrangement_hash=projection.arrangement_hash,
                audio_engine_version=ENGINE_VERSION,
                seed=SEED,
                timeout_seconds=240,
                maximum_output_bytes=64 * 1024 * 1024,
            )
            queued = await EnqueueFollowupMediaJob(media_uow)(
                EnqueueFollowupMediaJobRequest(
                    run_id=first.run_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    job_type=MediaJobType.RENDER_CANONICAL,
                    input_payload=payload.model_dump(mode="json"),
                    output_quality_profile=MediaQualityProfile.CANONICAL_STEM_V1,
                    idempotency_key=f"s1-stem-{track.track_id}-{invocation}",
                    deadline_seconds=300,
                )
            )
            await _execute_job(job_id=queued.job_id, settings=settings)
            stem_artifacts.append(await _artifact_for_job(media_uow, queued.job_id))
            trace_refs.append(f"job:{queued.job_id}")

        mp3_payload = ExportMp3JobPayload(
            project_id=project.project_id,
            revision_id=revision_id,
            source_artifact_id=master.artifact_id,
            source_content_hash=master.content_hash,
            timeout_seconds=180,
        )
        mp3_job = await EnqueueFollowupMediaJob(media_uow)(
            EnqueueFollowupMediaJobRequest(
                run_id=first.run_id,
                project_id=project.project_id,
                thread_id=thread_id,
                job_type=MediaJobType.TRANSCODE_EXPORT,
                input_payload=mp3_payload.model_dump(mode="json"),
                output_quality_profile=MediaQualityProfile.DELIVERY_MP3_V1,
                idempotency_key=f"s1-mp3-{invocation}",
                deadline_seconds=240,
            )
        )
        await _execute_job(job_id=mp3_job.job_id, settings=settings)
        mp3 = await _artifact_for_job(media_uow, mp3_job.job_id)
        if master.duration_seconds is None:
            raise RuntimeError("S1 Master duration metadata is missing")
        trace_refs.append(f"job:{mp3_job.job_id}")

        audio_inputs = (
            _bundle_input(
                master,
                filename="master.wav",
                profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            ),
            _bundle_input(
                mp3,
                filename="master.mp3",
                profile=MediaQualityProfile.DELIVERY_MP3_V1,
            ),
            *tuple(
                _bundle_input(
                    artifact,
                    filename=f"stem-{track.track_id}.wav",
                    profile=MediaQualityProfile.CANONICAL_STEM_V1,
                )
                for track, artifact in zip(arrangement.tracks, stem_artifacts, strict=True)
            ),
        )
        bundle_payload = ExportBundleJobPayload(
            project_id=project.project_id,
            revision_id=revision_id,
            seed=SEED,
            arrangement_hash=revision.content_hash,
            audio_inputs=audio_inputs,
            engine_version=ENGINE_VERSION,
            trace_refs=tuple(trace_refs),
        )
        bundle_job = await EnqueueFollowupMediaJob(media_uow)(
            EnqueueFollowupMediaJobRequest(
                run_id=first.run_id,
                project_id=project.project_id,
                thread_id=thread_id,
                job_type=MediaJobType.EXPORT_BUNDLE,
                input_payload=bundle_payload.model_dump(mode="json"),
                output_quality_profile=MediaQualityProfile.EXPORT_BUNDLE_V1,
                idempotency_key=f"s1-bundle-{invocation}",
                deadline_seconds=240,
            )
        )
        await _execute_job(job_id=bundle_job.job_id, settings=settings)
        bundle = await _bundle_for_job(media_uow, bundle_job.job_id)
        manifest_path = artifact_root / bundle.storage_prefix / "export-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if len(manifest["files"]) != 12:
            raise RuntimeError("S1 Export Manifest is incomplete")
        print(
            json.dumps(
                {
                    "project_id": str(project.project_id),
                    "revision_id": str(revision_id),
                    "run_id": str(first.run_id),
                    "duration_seconds": master.duration_seconds,
                    "master_bytes": master.byte_size,
                    "stem_count": len(stem_artifacts),
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
