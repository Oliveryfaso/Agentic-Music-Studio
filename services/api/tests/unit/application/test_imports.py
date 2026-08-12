from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from motif_forge.application.imports import MaterializeImport, MaterializeImportRequest
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    MediaQualityProfile,
)

from application.fakes import FakeTransaction


class FakeMediaTransaction:
    def __init__(self, artifact: AudioArtifact) -> None:
        self.artifact = artifact

    def __call__(self) -> FakeMediaTransaction:
        return self

    async def __aenter__(self) -> FakeMediaTransaction:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None:
        return self.artifact if self.artifact.artifact_id == artifact_id else None

    async def get_feature_artifact_for_source(self, *_: object) -> None:
        return None


def _artifact(project_id: UUID) -> AudioArtifact:
    return AudioArtifact(
        artifact_id=uuid4(),
        project_id=project_id,
        source_job_id=uuid4(),
        content_hash="a" * 64,
        byte_size=19_200,
        storage_key=f"protected/working-pcm/{project_id}/aa/{'a' * 64}.wav",
        media_role="normalized_import_audio",
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=1.0,
        bit_depth=16,
        encoder="ffmpeg",
        encoder_version="test",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        recipe_hash="b" * 64,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_materialize_import_commits_one_system_l1_revision_idempotently() -> None:
    projects = FakeTransaction()
    created = await CreateProject(projects)(
        CreateProjectRequest(
            name="Import",
            actor_id="test",
            idempotency_key="project-create-001",
        )
    )
    artifact = _artifact(created.project_id)
    use_case = MaterializeImport(projects, FakeMediaTransaction(artifact))  # type: ignore[arg-type]
    request = MaterializeImportRequest(
        project_id=created.project_id,
        branch_id=created.active_branch_id,
        base_revision_id=created.root_revision_id,
        normalized_artifact_id=artifact.artifact_id,
    )

    first = await use_case(request)
    replay = await use_case(request)

    assert first.actual_change_impact.name == "L1"
    assert replay.revision_id == first.revision_id
    assert replay.replayed is True
    revision = projects.revisions[first.revision_id]
    assert revision.arrangement_ir.tracks[0].clips[0].artifact_id == artifact.artifact_id  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_materialize_aligned_import_records_reversible_time_stretch_lineage() -> None:
    projects = FakeTransaction()
    created = await CreateProject(projects)(
        CreateProjectRequest(
            name="Aligned Import",
            actor_id="test",
            idempotency_key="project-create-aligned",
        )
    )
    derived = _artifact(created.project_id)
    original_artifact_id = uuid4()
    result = await MaterializeImport(projects, FakeMediaTransaction(derived))(  # type: ignore[arg-type]
        MaterializeImportRequest(
            project_id=created.project_id,
            branch_id=created.active_branch_id,
            base_revision_id=created.root_revision_id,
            normalized_artifact_id=derived.artifact_id,
            original_normalized_artifact_id=original_artifact_id,
            source_bpm=100.0,
            target_bpm=120.0,
        )
    )

    clip = projects.revisions[result.revision_id].arrangement_ir.tracks[0].clips[0]
    assert clip.time_stretch_ref is not None  # type: ignore[union-attr]
    assert clip.time_stretch_ref.source_artifact_id == original_artifact_id  # type: ignore[union-attr]
    assert clip.time_stretch_ref.preserve_pitch is True  # type: ignore[union-attr]
    assert clip.source_bpm == 100.0  # type: ignore[union-attr]
    assert clip.target_bpm == 120.0  # type: ignore[union-attr]
