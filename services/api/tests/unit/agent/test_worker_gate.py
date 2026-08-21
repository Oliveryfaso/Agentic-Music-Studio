from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from motif_forge.agent.worker_gate import persisted_worker_event_update, wait_for_job_event
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    MediaQualityProfile,
    RenderScope,
    WorkerEvent,
)


def test_persisted_completion_routes_to_artifact_validation_without_binary_state() -> None:
    job_id = uuid4()
    artifact = AudioArtifact(
        artifact_id=uuid4(),
        project_id=uuid4(),
        candidate_snapshot_id=uuid4(),
        arrangement_hash="a" * 64,
        render_scope=RenderScope.MASTER,
        source_job_id=job_id,
        content_hash="d" * 64,
        byte_size=2048,
        storage_key="sha256/dd/preview.mp3",
        media_role="candidate_preview",
        quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        container="mp3",
        codec="mp3",
        sample_rate_hz=48_000,
        channels=2,
        duration_seconds=20.0,
        bitrate_kbps=160,
        encoder="ffmpeg",
        encoder_version="7.1",
        lifecycle_class=ArtifactLifecycle.PROTECTED,
        created_at=datetime.now(UTC),
    )
    event = WorkerEvent(
        event_id="event-completed",
        job_id=job_id,
        event_type="job.completed",
        artifact=artifact,
        occurred_at=datetime.now(UTC),
    )

    update = persisted_worker_event_update(event)

    assert update == {
        "phase": "worker_result_ready",
        "pending_job_id": None,
        "artifact_refs": [str(artifact.artifact_id)],
        "pending_action": "validate_artifact",
    }
    assert "storage_key" not in update


def test_persisted_retryable_failure_uses_rule_route_not_model_decision() -> None:
    event = WorkerEvent(
        event_id="event-retry",
        job_id=uuid4(),
        event_type="job.failed_retryable",
        error_code="WORKER_HEARTBEAT_TIMEOUT",
        occurred_at=datetime.now(UTC),
    )

    update = persisted_worker_event_update(event)

    assert update["phase"] == "waiting_worker_retry"
    assert update["pending_action"] == "retry_job"
    assert update["error_code"] == "WORKER_HEARTBEAT_TIMEOUT"


def test_wait_for_job_event_interrupts_and_resumes_same_checkpoint() -> None:
    job_id = uuid4()
    artifact_id = uuid4()
    builder = StateGraph(dict)
    builder.add_node("WaitForJobEvent", wait_for_job_event)
    builder.add_edge(START, "WaitForJobEvent")
    builder.add_edge("WaitForJobEvent", END)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": f"worker-wait-{uuid4()}"}}

    interrupted = graph.invoke({"pending_job_id": str(job_id)}, config)
    assert interrupted["pending_job_id"] == str(job_id)

    resumed = graph.invoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(uuid4()),
                "thread_id": config["configurable"]["thread_id"],
                "job_id": str(job_id),
                "status": "succeeded",
                "artifact_id": str(artifact_id),
                "error_code": None,
            }
        ),
        config,
    )

    assert resumed["phase"] == "worker_result_ready"
    assert resumed["artifact_refs"] == [str(artifact_id)]
    assert resumed["pending_action"] == "validate_artifact"
