from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID

import pytest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.generation import (
    CollectCompleteExportArtifact,
    CompleteExportCursor,
    EnqueueNextCompleteExportJob,
    build_export_bundle_payload,
)
from motif_forge.application.media_jobs import EnqueueFollowupMediaJob, EnqueueMediaJob
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.ir import TrackRole
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
    JobStatus,
    MediaJob,
    MediaQualityProfile,
    MediaRun,
    RenderScope,
    RunStatus,
)
from motif_forge.domain.revisions import AuthorKind, ChangeImpact, Revision, VersionRefs
from pydantic import ValidationError

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000031")
REVISION_ID = UUID("20000000-0000-4000-8000-000000000031")
BRANCH_ID = UUID("30000000-0000-4000-8000-000000000031")


class FakeExportTransaction:
    def __init__(self, revision: Revision) -> None:
        self.revision = revision
        self.jobs: dict[UUID, MediaJob] = {}
        self.runs: dict[UUID, MediaRun] = {}
        self.artifacts: dict[UUID, AudioArtifact] = {}

    def __call__(self) -> FakeExportTransaction:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    async def get_revision(self, revision_id: UUID) -> Revision | None:
        return self.revision if revision_id == self.revision.revision_id else None

    async def find_media_job_by_key(
        self, *, project_id: UUID, job_type: str, idempotency_key: str
    ) -> MediaJob | None:
        return next(
            (
                job
                for job in self.jobs.values()
                if job.project_id == project_id
                and job.job_type == job_type
                and job.idempotency_key == idempotency_key
            ),
            None,
        )

    async def get_media_job(self, job_id: UUID, *, for_update: bool = False) -> MediaJob | None:
        del for_update
        return self.jobs.get(job_id)

    async def get_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None:
        return self.artifacts.get(artifact_id)

    async def insert_media_run_job(self, **kwargs: object) -> None:
        run = kwargs["run"]
        job = kwargs["job"]
        assert isinstance(run, MediaRun)
        assert isinstance(job, MediaJob)
        self.runs[run.run_id] = run
        self.jobs[job.job_id] = job

    async def append_media_job_to_run(self, **kwargs: object) -> bool:
        job = kwargs["job"]
        expected_thread_id = kwargs["expected_thread_id"]
        assert isinstance(job, MediaJob)
        run = self.runs.get(job.run_id)
        if run is None or run.thread_id != expected_thread_id:
            return False
        self.jobs[job.job_id] = job
        self.runs[run.run_id] = run.model_copy(
            update={"waiting_for_job_id": job.job_id, "status": RunStatus.WAITING_WORKER}
        )
        return True


def _revision() -> Revision:
    arrangement = build_s1_composition(PROJECT_ID, seed=31).arrangement
    return Revision(
        revision_id=REVISION_ID,
        project_id=PROJECT_ID,
        parent_revision_id=UUID(int=1),
        created_on_branch_id=BRANCH_ID,
        arrangement_ir=arrangement,
        content_hash=build_s1_composition(PROJECT_ID, seed=31).content_hash,
        command_batch_id=UUID(int=2),
        change_impact_predicted=ChangeImpact.L3,
        change_impact_actual=ChangeImpact.L3,
        author_kind=AuthorKind.AGENT,
        created_by="agent:test",
        reason_code="GENERATED",
        versions=VersionRefs(audio_engine="motif-forge-audio-engine.v1"),
        created_at=NOW,
    )


def _artifact(
    *,
    artifact_id: int,
    job_id: UUID,
    profile: MediaQualityProfile,
    scope: RenderScope,
    track_ids: tuple[UUID, ...] = (),
    revision_id: UUID = REVISION_ID,
    arrangement_hash: str | None = None,
) -> AudioArtifact:
    return AudioArtifact(
        artifact_id=UUID(int=artifact_id),
        project_id=PROJECT_ID,
        revision_id=revision_id,
        arrangement_hash=arrangement_hash or _revision().content_hash,
        render_scope=scope,
        render_track_ids=track_ids,
        source_job_id=job_id,
        content_hash=f"{artifact_id:064x}",
        byte_size=4096,
        storage_key=f"protected/test/{artifact_id}.audio",
        media_role="canonical_render"
        if profile is not MediaQualityProfile.DELIVERY_MP3_V1
        else "delivery_mp3",
        quality_profile=profile,
        container="mp3" if profile is MediaQualityProfile.DELIVERY_MP3_V1 else "wav",
        codec="mp3" if profile is MediaQualityProfile.DELIVERY_MP3_V1 else "pcm",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=72.0,
        bitrate_kbps=256 if profile is MediaQualityProfile.DELIVERY_MP3_V1 else None,
        bit_depth=None if profile is MediaQualityProfile.DELIVERY_MP3_V1 else 24,
        encoder="test",
        encoder_version="1",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        availability=ArtifactAvailability.AVAILABLE,
        created_at=NOW,
    )


def _services(
    transaction: FakeExportTransaction,
) -> tuple[EnqueueNextCompleteExportJob, CollectCompleteExportArtifact]:
    enqueue = EnqueueNextCompleteExportJob(
        transaction,
        enqueue_first=EnqueueMediaJob(transaction),
        enqueue_followup=EnqueueFollowupMediaJob(transaction),
    )
    return enqueue, CollectCompleteExportArtifact(transaction)


@pytest.mark.asyncio
async def test_cursor_orders_complete_export_and_uses_stable_master_key() -> None:
    transaction = FakeExportTransaction(_revision())
    enqueue, _ = _services(transaction)
    cursor = CompleteExportCursor(
        project_id=PROJECT_ID,
        revision_id=REVISION_ID,
        thread_id="generate-export-31",
        seed=31,
    )

    first = await enqueue(cursor)
    replay = await enqueue(cursor)

    assert cursor.pending_steps == (
        "master",
        "stem:pad",
        "stem:melody",
        "stem:bass",
        "stem:rhythm",
        "mp3",
        "bundle",
    )
    assert replay.pending_job_id == first.pending_job_id
    assert replay.media_run_id == first.media_run_id
    assert len(transaction.jobs) == 1
    job = transaction.jobs[first.pending_job_id]
    assert job.idempotency_key == first.pending_idempotency_key
    assert job.input_payload["revision_id"] == str(REVISION_ID)
    assert job.input_payload["arrangement_hash"] == transaction.revision.content_hash


@pytest.mark.asyncio
async def test_completion_replay_advances_once_and_stem_reloads_authoritative_revision() -> None:
    transaction = FakeExportTransaction(_revision())
    enqueue, collect = _services(transaction)
    waiting = await enqueue(
        CompleteExportCursor(
            project_id=PROJECT_ID,
            revision_id=REVISION_ID,
            thread_id="generate-export-31",
            seed=31,
        )
    )
    master = _artifact(
        artifact_id=401,
        job_id=waiting.pending_job_id,
        profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        scope=RenderScope.MASTER,
    )
    transaction.artifacts[master.artifact_id] = master
    transaction.jobs[waiting.pending_job_id] = transaction.jobs[waiting.pending_job_id].model_copy(
        update={"status": JobStatus.SUCCEEDED, "result_artifact_id": master.artifact_id}
    )

    advanced = await collect(waiting)
    replay = await collect(advanced, completed_job_id=waiting.pending_job_id)
    stem_waiting = await enqueue(advanced)

    assert replay == advanced
    assert advanced.completed_steps == ("master",)
    assert stem_waiting.pending_steps[0] == "stem:pad"
    stem_job = transaction.jobs[stem_waiting.pending_job_id]
    pad = next(
        track
        for track in transaction.revision.arrangement_ir.tracks
        if track.role is TrackRole.HARMONY
    )
    assert stem_job.input_payload["render_track_ids"] == [str(pad.track_id)]
    assert stem_job.input_payload["arrangement_hash"] == transaction.revision.content_hash


@pytest.mark.asyncio
async def test_wrong_artifact_lineage_is_rejected_before_cursor_advances() -> None:
    transaction = FakeExportTransaction(_revision())
    enqueue, collect = _services(transaction)
    waiting = await enqueue(
        CompleteExportCursor(
            project_id=PROJECT_ID,
            revision_id=REVISION_ID,
            thread_id="generate-export-31",
            seed=31,
        )
    )
    wrong = _artifact(
        artifact_id=402,
        job_id=waiting.pending_job_id,
        profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        scope=RenderScope.MASTER,
        revision_id=UUID(int=999),
    )
    transaction.artifacts[wrong.artifact_id] = wrong
    transaction.jobs[waiting.pending_job_id] = transaction.jobs[waiting.pending_job_id].model_copy(
        update={"status": JobStatus.SUCCEEDED, "result_artifact_id": wrong.artifact_id}
    )

    with pytest.raises(ApplicationError, match="EXPORT_ARTIFACT_LINEAGE_MISMATCH"):
        await collect(waiting)


@pytest.mark.asyncio
async def test_artifact_from_a_different_job_is_rejected() -> None:
    transaction = FakeExportTransaction(_revision())
    enqueue, collect = _services(transaction)
    waiting = await enqueue(
        CompleteExportCursor(
            project_id=PROJECT_ID,
            revision_id=REVISION_ID,
            thread_id="generate-export-31",
            seed=31,
        )
    )
    wrong_source = _artifact(
        artifact_id=403,
        job_id=UUID(int=999),
        profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        scope=RenderScope.MASTER,
    )
    transaction.artifacts[wrong_source.artifact_id] = wrong_source
    transaction.jobs[waiting.pending_job_id] = transaction.jobs[waiting.pending_job_id].model_copy(
        update={"status": JobStatus.SUCCEEDED, "result_artifact_id": wrong_source.artifact_id}
    )

    with pytest.raises(ApplicationError, match="EXPORT_ARTIFACT_LINEAGE_MISMATCH"):
        await collect(waiting)


def test_bundle_payload_keeps_only_logical_audio_references() -> None:
    revision = _revision()
    track_ids = tuple(track.track_id for track in revision.arrangement_ir.tracks)
    artifacts = (
        _artifact(
            artifact_id=501,
            job_id=UUID(int=1),
            profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            scope=RenderScope.MASTER,
        ),
        *tuple(
            _artifact(
                artifact_id=502 + index,
                job_id=UUID(int=2 + index),
                profile=MediaQualityProfile.CANONICAL_STEM_V1,
                scope=RenderScope.STEM,
                track_ids=(track_id,),
            )
            for index, track_id in enumerate(track_ids)
        ),
        _artifact(
            artifact_id=506,
            job_id=UUID(int=6),
            profile=MediaQualityProfile.DELIVERY_MP3_V1,
            scope=RenderScope.MASTER,
        ),
    )

    payload = build_export_bundle_payload(
        revision=revision, seed=31, artifacts=artifacts, trace_refs=("run:31",)
    )
    dumped = payload.model_dump(mode="json")

    assert len(payload.audio_inputs) == 6
    assert "storage_key" not in str(dumped)
    assert "audio_bytes" not in str(dumped)
    assert {item.artifact_id for item in payload.audio_inputs} == {
        item.artifact_id for item in artifacts
    }


def test_cursor_rejects_non_prefix_or_inconsistent_checkpoint_state() -> None:
    with pytest.raises(ValidationError):
        CompleteExportCursor(
            project_id=PROJECT_ID,
            revision_id=REVISION_ID,
            thread_id="generate-export-31",
            seed=31,
            completed_steps=("master", "stem:melody"),
        )
    with pytest.raises(ValidationError):
        CompleteExportCursor(
            project_id=PROJECT_ID,
            revision_id=REVISION_ID,
            thread_id="generate-export-31",
            seed=31,
            media_run_id=UUID(int=30),
            completed_steps=("master",),
            completed_job_ids=(UUID(int=31),),
            audio_artifact_ids=(),
        )


@pytest.mark.asyncio
async def test_enqueue_revalidates_previously_collected_artifacts() -> None:
    transaction = FakeExportTransaction(_revision())
    enqueue, collect = _services(transaction)
    waiting = await enqueue(
        CompleteExportCursor(
            project_id=PROJECT_ID,
            revision_id=REVISION_ID,
            thread_id="generate-export-31",
            seed=31,
        )
    )
    master = _artifact(
        artifact_id=601,
        job_id=waiting.pending_job_id,
        profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        scope=RenderScope.MASTER,
    )
    transaction.artifacts[master.artifact_id] = master
    transaction.jobs[waiting.pending_job_id] = transaction.jobs[waiting.pending_job_id].model_copy(
        update={"status": JobStatus.SUCCEEDED, "result_artifact_id": master.artifact_id}
    )
    advanced = await collect(waiting)
    transaction.artifacts[master.artifact_id] = master.model_copy(
        update={"arrangement_hash": "f" * 64}
    )

    with pytest.raises(ApplicationError, match="EXPORT_ARTIFACT_LINEAGE_MISMATCH"):
        await enqueue(advanced)
