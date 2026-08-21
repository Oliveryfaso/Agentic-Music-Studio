from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from motif_forge.application.candidate_previews import (
    CollectCandidatePreview,
    EnqueueCandidatePreview,
    EnqueueCandidatePreviewRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.rendering import build_candidate_preview_payload
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    JobStatus,
    MediaQualityProfile,
    RebuildRecipe,
    RenderScope,
)
from motif_forge.domain.revisions import VersionRefs, create_candidate_snapshot

from .fakes import FakeTransaction
from .test_media_jobs import FakeMediaJobTransaction

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


async def _snapshot():
    projects = FakeTransaction()
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name="candidate preview",
            actor_id="human",
            idempotency_key="candidate-preview-project",
        )
    )
    base = projects.revisions[project.root_revision_id]
    build = build_s1_composition(project.project_id, seed=7)
    return create_candidate_snapshot(
        base_revision=base,
        candidate_ir=build.arrangement,
        candidate_id=uuid4(),
        commands=build.commands,
        source_run_id=uuid4(),
        versions=VersionRefs(compiler="candidate-preview-test.v1"),
        created_at=NOW,
    )


class CandidateMediaTransaction(FakeMediaJobTransaction):
    def __init__(self, snapshot) -> None:
        super().__init__()
        self.snapshot = snapshot

    async def get_candidate_snapshot(self, candidate_snapshot_id):
        return (
            self.snapshot
            if self.snapshot.candidate_snapshot_id == candidate_snapshot_id
            else None
        )


@pytest.mark.asyncio
async def test_payload_and_enqueue_bind_snapshot_without_revision() -> None:
    snapshot = await _snapshot()
    payload = build_candidate_preview_payload(snapshot, seed=0)
    assert payload.candidate_snapshot_id == snapshot.candidate_snapshot_id
    assert payload.quality_profile is MediaQualityProfile.CANDIDATE_PREVIEW_V1
    assert payload.render_scope is RenderScope.MASTER
    assert "revision_id" not in type(payload).model_fields

    transaction = CandidateMediaTransaction(snapshot)
    service = EnqueueCandidatePreview(transaction, clock=lambda: NOW)
    request = EnqueueCandidatePreviewRequest(
        project_id=snapshot.project_id,
        candidate_snapshot_id=snapshot.candidate_snapshot_id,
        expected_candidate_content_hash=snapshot.candidate_content_hash,
        thread_id="candidate-preview-thread",
        seed=0,
        idempotency_key="candidate-preview-a",
    )
    first = await service(request)
    replay = await service(request)
    assert replay.job_id == first.job_id
    assert replay.replayed is True
    assert len(transaction.jobs) == 1


@pytest.mark.asyncio
async def test_collect_requires_exact_candidate_artifact_lineage() -> None:
    snapshot = await _snapshot()
    transaction = CandidateMediaTransaction(snapshot)
    cursor = await EnqueueCandidatePreview(transaction, clock=lambda: NOW)(
        EnqueueCandidatePreviewRequest(
            project_id=snapshot.project_id,
            candidate_snapshot_id=snapshot.candidate_snapshot_id,
            expected_candidate_content_hash=snapshot.candidate_content_hash,
            thread_id="candidate-preview-thread",
            seed=0,
            idempotency_key="candidate-preview-b",
        )
    )
    job = transaction.jobs[cursor.job_id]
    recipe = RebuildRecipe(
        recipe_id=uuid4(),
        recipe_kind="render",
        parameters={"candidate_snapshot_id": str(snapshot.candidate_snapshot_id)},
        engine="test-renderer",
        engine_version="test-renderer.v1",
        policy_version="candidate-preview-render.v1",
        output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        expected_container="mp3",
        expected_codec="mp3",
        expected_sample_rate_hz=48_000,
        expected_channels=2,
        validation_rules=("candidate-snapshot-lineage.v1",),
        idempotency_key="candidate-preview-rebuild",
    )
    artifact = AudioArtifact(
        artifact_id=uuid4(),
        project_id=snapshot.project_id,
        candidate_snapshot_id=snapshot.candidate_snapshot_id,
        arrangement_hash=snapshot.candidate_content_hash,
        render_scope=RenderScope.MASTER,
        source_job_id=job.job_id,
        content_hash="b" * 64,
        byte_size=4096,
        storage_key=(
            f"rebuildable/candidate-previews/{snapshot.project_id}/"
            f"{snapshot.candidate_snapshot_id}/{'b' * 64}-preview.mp3"
        ),
        media_role="candidate_preview",
        quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        container="mp3",
        codec="mp3",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=60.0,
        bitrate_kbps=160,
        encoder="ffmpeg-libmp3lame",
        encoder_version="ffmpeg-system.v1",
        lifecycle_class=ArtifactLifecycle.REBUILDABLE,
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=NOW,
    )
    transaction.artifacts[artifact.artifact_id] = artifact
    transaction.jobs[job.job_id] = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "result_artifact_id": artifact.artifact_id,
        }
    )

    completed = await CollectCandidatePreview(transaction)(cursor, job.job_id)
    assert completed.preview_artifact_id == artifact.artifact_id
