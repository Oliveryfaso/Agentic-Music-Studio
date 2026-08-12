"""Deterministic state update for persisted Worker events.

The Inbox/Job transaction must accept the event before this update is applied to a
LangGraph checkpoint. It is intentionally a reusable node contract, not a second Graph.
"""

from __future__ import annotations

import json
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.types import interrupt

from motif_forge.domain.media_jobs import WorkerEvent, WorkerResumePayload


class WorkerGateUpdate(TypedDict):
    phase: Literal["worker_result_ready", "waiting_worker_retry", "worker_failed"]
    pending_job_id: None
    artifact_refs: list[str]
    error_code: NotRequired[str]
    last_resume_event_id: NotRequired[str]
    pending_action: Literal["validate_artifact", "retry_job", "route_error"]


def persisted_worker_event_update(event: WorkerEvent) -> WorkerGateUpdate:
    """Map an already-deduplicated Worker event to a compact checkpoint update."""

    if event.event_type == "job.completed":
        if event.artifact is None:  # WorkerEvent validation makes this defensive only.
            raise ValueError("completed worker event is missing its artifact")
        return WorkerGateUpdate(
            phase="worker_result_ready",
            pending_job_id=None,
            artifact_refs=[str(event.artifact.artifact_id)],
            pending_action="validate_artifact",
        )
    if event.event_type == "job.failed_retryable":
        return WorkerGateUpdate(
            phase="waiting_worker_retry",
            pending_job_id=None,
            artifact_refs=[],
            error_code=event.error_code or "WORKER_RETRYABLE_FAILURE",
            pending_action="retry_job",
        )
    return WorkerGateUpdate(
        phase="worker_failed",
        pending_job_id=None,
        artifact_refs=[],
        error_code=event.error_code or "WORKER_TERMINAL_FAILURE",
        pending_action="route_error",
    )


def persisted_worker_resume_update(payload: WorkerResumePayload) -> WorkerGateUpdate:
    """Map the compact, transaction-backed resume payload into Parent Graph state."""

    if payload.status == "succeeded":
        if payload.artifact_id is None:  # Schema validation makes this defensive only.
            raise ValueError("successful Worker resume is missing artifact_id")
        update = WorkerGateUpdate(
            phase="worker_result_ready",
            pending_job_id=None,
            artifact_refs=[str(payload.artifact_id)],
            pending_action="validate_artifact",
        )
    else:
        update = WorkerGateUpdate(
            phase="worker_failed",
            pending_job_id=None,
            artifact_refs=[],
            error_code=payload.error_code or "WORKER_TERMINAL_FAILURE",
            pending_action="route_error",
        )
    if payload.resume_event_id is not None:
        update["last_resume_event_id"] = payload.resume_event_id
    return update


def wait_for_job_event(state: dict[str, Any]) -> WorkerGateUpdate:
    """Reusable Parent Graph node; never compile it as a second production Graph."""

    pending_job_id = state.get("pending_job_id")
    if not isinstance(pending_job_id, str):
        raise ValueError("WaitForJobEvent requires pending_job_id")
    resumed = interrupt(
        {
            "kind": "worker_job",
            "job_id": pending_job_id,
            "phase": "waiting_worker",
        }
    )
    payload = WorkerResumePayload.model_validate_json(json.dumps(resumed), strict=True)
    if str(payload.job_id) != pending_job_id:
        raise ValueError("Worker resume payload does not match pending_job_id")
    expected_run_id = state.get("run_id")
    if isinstance(expected_run_id, str) and str(payload.run_id) != expected_run_id:
        raise ValueError("Worker resume payload does not match run_id")
    expected_thread_id = state.get("thread_id")
    if isinstance(expected_thread_id, str) and payload.thread_id != expected_thread_id:
        raise ValueError("Worker resume payload does not match thread_id")
    return persisted_worker_resume_update(payload)
