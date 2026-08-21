from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from motif_forge.application.errors import IdempotencyKeyReusedError
from motif_forge.application.media_jobs import (
    ApplyWorkerEvent,
    EnqueueFollowupMediaJob,
    EnqueueFollowupMediaJobRequest,
    EnqueueMediaJob,
    EnqueueMediaJobRequest,
    StartArtifactRehydration,
    StartArtifactRehydrationRequest,
    _compile_rehydrate_payload,
)
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactLifecycle,
    AudioArtifact,
    CandidatePreviewJobPayload,
    JobStatus,
    MediaJob,
    MediaJobType,
    MediaQualityProfile,
    MediaRun,
    RebuildInputArtifact,
    RebuildRecipe,
    RenderScope,
    RunStatus,
    WorkerEvent,
)


class FakeMediaJobTransaction:
    def __init__(self) -> None:
        self.jobs: dict[UUID, MediaJob] = {}
        self.runs: dict[UUID, MediaRun] = {}
        self.artifacts: dict[UUID, AudioArtifact] = {}
        self.receipts: set[tuple[str, str]] = set()
        self.outbox_topics: list[str] = []

    def __call__(self) -> FakeMediaJobTransaction:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

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

    async def get_feature_artifact(self, artifact_id: UUID) -> None:
        del artifact_id
        return None

    async def get_feature_artifact_for_source(self, *_: object) -> None:
        return None

    async def lock_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None:
        return self.artifacts.get(artifact_id)

    async def lock_feature_artifact(self, artifact_id: UUID) -> None:
        del artifact_id
        return None

    async def insert_feature_rehydration_run_job(self, **_: object) -> None:
        raise AssertionError("Feature rehydration is not used by this fake")

    async def has_inbox_receipt(self, *, consumer: str, event_id: str) -> bool:
        return (consumer, event_id) in self.receipts

    async def insert_media_run_job(
        self,
        *,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None:
        del run_event_id, job_event_id, outbox_event_id
        self.runs[run.run_id] = run
        self.jobs[job.job_id] = job
        self.outbox_topics.append("media.job.dispatch.requested")

    async def insert_rehydration_run_job(
        self,
        *,
        target_artifact_id: UUID,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None:
        target = self.artifacts[target_artifact_id]
        self.artifacts[target_artifact_id] = target.model_copy(
            update={
                "availability": ArtifactAvailability.REHYDRATING,
                "rehydration_job_id": job.job_id,
            }
        )
        await self.insert_media_run_job(
            run=run,
            job=job,
            run_event_id=run_event_id,
            job_event_id=job_event_id,
            outbox_event_id=outbox_event_id,
        )

    async def append_media_job_to_run(
        self,
        *,
        expected_thread_id: str,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> bool:
        del run_event_id, job_event_id, outbox_event_id
        run = self.runs.get(job.run_id)
        if run is None or run.thread_id != expected_thread_id:
            return False
        self.jobs[job.job_id] = job
        self.runs[run.run_id] = run.model_copy(
            update={"waiting_for_job_id": job.job_id, "status": RunStatus.WAITING_WORKER}
        )
        self.outbox_topics.append("media.job.dispatch.requested")
        return True

    async def apply_worker_event(
        self,
        *,
        event: WorkerEvent,
        updated_job: MediaJob,
        run_status: RunStatus,
        artifact: AudioArtifact | None,
        feature_artifacts: tuple[object, ...],
        validated_source_artifact: AudioArtifact | None,
        consumer: str,
        inbox_receipt_id: UUID,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
        outbox_topic: str,
    ) -> AudioArtifact | None:
        del feature_artifacts, inbox_receipt_id, run_event_id, job_event_id, outbox_event_id
        self.jobs[updated_job.job_id] = updated_job
        run = self.runs[updated_job.run_id]
        self.runs[run.run_id] = run.model_copy(
            update={"status": run_status, "updated_at": event.occurred_at}
        )
        self.receipts.add((consumer, event.event_id))
        self.outbox_topics.append(outbox_topic)
        if artifact is not None:
            self.artifacts[artifact.artifact_id] = artifact
        if validated_source_artifact is not None:
            self.artifacts[validated_source_artifact.artifact_id] = validated_source_artifact
        return artifact


def _request(project_id: UUID) -> EnqueueMediaJobRequest:
    return EnqueueMediaJobRequest(
        project_id=project_id,
        thread_id="thread-1",
        run_type="candidate_preview",
        job_type=MediaJobType.RENDER_PREVIEW,
        input_payload={"candidate_snapshot_id": str(uuid4())},
        output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        idempotency_key="render-candidate-a",
    )


def _artifact(project_id: UUID, job_id: UUID, created_at: datetime) -> AudioArtifact:
    return AudioArtifact(
        artifact_id=uuid4(),
        project_id=project_id,
        candidate_snapshot_id=uuid4(),
        arrangement_hash="a" * 64,
        render_scope=RenderScope.MASTER,
        source_job_id=job_id,
        content_hash="b" * 64,
        byte_size=1000,
        storage_key="sha256/bb/preview.mp3",
        media_role="candidate_preview",
        quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        container="mp3",
        codec="mp3",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=30.0,
        bitrate_kbps=160,
        encoder="ffmpeg",
        encoder_version="7.1",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        created_at=created_at,
    )


def test_candidate_render_recipe_compiles_to_executable_rehydration_payload() -> None:
    project_id = uuid4()
    snapshot_id = uuid4()
    artifact_id = uuid4()
    now = datetime.now(UTC)
    audio_graph = {
        "schemaVersion": "audio-graph-spec.v1",
        "engineVersion": "motif-forge-audio-engine.v1",
        "sampleRate": 48_000,
        "channels": 2,
    }
    audio_graph_hash = hashlib.sha256(
        json.dumps(audio_graph, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    recipe = RebuildRecipe(
        recipe_id=uuid4(),
        recipe_kind="render",
        parameters={
            "candidate_snapshot_id": str(snapshot_id),
            "candidate_content_hash": "a" * 64,
            "audio_graph": audio_graph,
            "audio_graph_hash": audio_graph_hash,
            "audio_engine_version": "motif-forge-audio-engine.v1",
            "seed": 0,
            "bitrate_kbps": 160,
            "timeout_seconds": 240,
            "maximum_output_bytes": 64 * 1024 * 1024,
        },
        engine="motif-forge-chromium-renderer+ffmpeg-libmp3lame",
        engine_version="motif-forge-audio-engine.v1",
        policy_version="candidate-preview-render.v1",
        output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        expected_container="mp3",
        expected_codec="mp3",
        expected_sample_rate_hz=48_000,
        expected_channels=2,
        validation_rules=("candidate-snapshot-lineage.v1",),
        idempotency_key="candidate-preview-rebuild",
    )
    target = AudioArtifact(
        artifact_id=artifact_id,
        project_id=project_id,
        candidate_snapshot_id=snapshot_id,
        arrangement_hash="a" * 64,
        render_scope=RenderScope.MASTER,
        source_job_id=uuid4(),
        content_hash="c" * 64,
        byte_size=4096,
        storage_key=f"rebuildable/candidate-previews/{project_id}/{snapshot_id}/preview.mp3",
        media_role="candidate_preview",
        quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        container="mp3",
        codec="mp3",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=30.0,
        bitrate_kbps=160,
        encoder="ffmpeg-libmp3lame",
        encoder_version="ffmpeg-system.v1",
        lifecycle_class=ArtifactLifecycle.REBUILDABLE,
        availability=ArtifactAvailability.EVICTED,
        recipe_hash=recipe.content_hash,
        rebuild_recipe=recipe,
        created_at=now,
        evicted_at=now,
    )

    payload = _compile_rehydrate_payload(target, project_id=project_id)

    assert isinstance(payload, CandidatePreviewJobPayload)
    assert payload.target_artifact_id == artifact_id
    assert payload.expected_output_content_hash == target.content_hash
    assert payload.expected_recipe_hash == recipe.content_hash


@pytest.mark.asyncio
async def test_enqueue_is_atomic_and_idempotent() -> None:
    transaction = FakeMediaJobTransaction()
    project_id = uuid4()
    use_case = EnqueueMediaJob(transaction)
    request = _request(project_id)

    first = await use_case(request)
    replayed = await use_case(request)

    assert replayed.job_id == first.job_id
    assert replayed.replayed is True
    assert len(transaction.jobs) == 1
    assert transaction.outbox_topics == ["media.job.dispatch.requested"]


@pytest.mark.asyncio
async def test_reused_idempotency_key_with_different_payload_is_rejected() -> None:
    transaction = FakeMediaJobTransaction()
    project_id = uuid4()
    use_case = EnqueueMediaJob(transaction)
    request = _request(project_id)
    await use_case(request)

    with pytest.raises(IdempotencyKeyReusedError):
        await use_case(
            request.model_copy(update={"input_payload": {"candidate_snapshot_id": str(uuid4())}})
        )


@pytest.mark.asyncio
async def test_worker_completion_requests_graph_resume_exactly_once() -> None:
    transaction = FakeMediaJobTransaction()
    project_id = uuid4()
    queued = await EnqueueMediaJob(transaction)(_request(project_id))
    occurred_at = datetime.now(UTC)
    artifact = _artifact(project_id, queued.job_id, occurred_at)
    event = WorkerEvent(
        event_id="worker-event-1",
        job_id=queued.job_id,
        event_type="job.completed",
        artifact=artifact,
        occurred_at=occurred_at,
    )

    first = await ApplyWorkerEvent(transaction)(event)
    replayed = await ApplyWorkerEvent(transaction)(event)

    assert first.status is JobStatus.SUCCEEDED
    assert first.artifact_id == artifact.artifact_id
    assert replayed.replayed is True
    assert transaction.outbox_topics.count("graph.resume.requested") == 1
    assert transaction.runs[queued.run_id].status is RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_followup_job_reuses_existing_run_and_is_idempotent() -> None:
    transaction = FakeMediaJobTransaction()
    project_id = uuid4()
    initial = await EnqueueMediaJob(transaction)(_request(project_id))
    request = EnqueueFollowupMediaJobRequest(
        run_id=initial.run_id,
        project_id=project_id,
        thread_id="thread-1",
        job_type=MediaJobType.TIME_STRETCH,
        input_payload={
            "schema_version": "time-stretch-job.v1",
            "source_artifact_id": str(uuid4()),
            "source_bpm": 100.0,
            "target_bpm": 120.0,
            "preserve_pitch": True,
            "timeout_seconds": 60.0,
        },
        output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        idempotency_key="import-alignment-followup",
    )

    first = await EnqueueFollowupMediaJob(transaction)(request)
    replay = await EnqueueFollowupMediaJob(transaction)(request)

    assert first.run_id == initial.run_id
    assert replay.job_id == first.job_id
    assert replay.replayed is True
    assert transaction.runs[initial.run_id].waiting_for_job_id == first.job_id


@pytest.mark.asyncio
async def test_rehydration_atomically_claims_evicted_artifact_and_is_idempotent() -> None:
    transaction = FakeMediaJobTransaction()
    project_id = uuid4()
    source_job_id = uuid4()
    source = AudioArtifact(
        artifact_id=uuid4(),
        project_id=project_id,
        source_job_id=source_job_id,
        content_hash="1" * 64,
        byte_size=1_024,
        storage_key="protected/source.wav",
        media_role="normalized_import_audio",
        quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        container="wav",
        codec="pcm",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=2.0,
        bit_depth=16,
        encoder="ffmpeg",
        encoder_version="7.1",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        created_at=datetime.now(UTC),
    )
    recipe = RebuildRecipe(
        recipe_id=uuid4(),
        recipe_kind="time_stretch",
        input_artifacts=(
            RebuildInputArtifact(artifact_id=source.artifact_id, content_hash=source.content_hash),
        ),
        parameters={
            "source_bpm": 120.0,
            "target_bpm": 100.0,
            "preserve_pitch": True,
            "timeout_seconds": 60.0,
        },
        engine="ffmpeg-atempo",
        engine_version="7.1",
        policy_version="time-stretch-quality-policy.v1",
        output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
        expected_container="wav",
        expected_codec="pcm",
        expected_sample_rate_hz=48_000,
        expected_channels=2,
        expected_bit_depth=16,
        validation_rules=("duration-tolerance.v1",),
        idempotency_key="rehydrate-recipe-contract",
    )
    target = source.model_copy(
        update={
            "artifact_id": uuid4(),
            "source_job_id": uuid4(),
            "content_hash": "2" * 64,
            "storage_key": "derived/22/target.wav",
            "lifecycle_class": ArtifactLifecycle.REBUILDABLE,
            "rebuild_recipe": recipe,
            "recipe_hash": recipe.content_hash,
            "availability": ArtifactAvailability.EVICTED,
            "evicted_at": datetime.now(UTC),
        }
    )
    transaction.artifacts[source.artifact_id] = source
    transaction.artifacts[target.artifact_id] = target
    use_case = StartArtifactRehydration(transaction)
    request = StartArtifactRehydrationRequest(
        project_id=project_id,
        artifact_id=target.artifact_id,
        thread_id="rehydrate-thread",
        idempotency_key="rehydrate-public-key",
    )

    first = await use_case(request)
    replay = await use_case(request)

    claimed = transaction.artifacts[target.artifact_id]
    assert claimed.availability is ArtifactAvailability.REHYDRATING
    assert claimed.rehydration_job_id == first.job_id
    assert transaction.jobs[first.job_id].job_type is MediaJobType.REHYDRATE
    assert replay.job_id == first.job_id
    assert replay.replayed is True
