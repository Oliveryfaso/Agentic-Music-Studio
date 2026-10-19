"""Deterministic export nodes mounted in the existing Parent Graph."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from langgraph.types import interrupt

from motif_forge.application.errors import ApplicationError
from motif_forge.application.revision_exports import RevisionExportRequest
from motif_forge.domain.export_plan import CompleteExportCursorV2
from motif_forge.domain.media_jobs import WorkerResumePayload


class RevisionExportNodes:
    def __init__(
        self,
        *,
        prepare: Callable[..., Awaitable[CompleteExportCursorV2]],
        enqueue: Callable[..., Awaitable[Any]],
        collect: Callable[..., Awaitable[Any]],
        cancel: Callable[..., Awaitable[None]],
    ) -> None:
        self._prepare, self._enqueue, self._collect, self._cancel = (
            prepare,
            enqueue,
            collect,
            cancel,
        )

    async def validate(self, state: Any) -> dict[str, Any]:
        try:
            request = RevisionExportRequest.model_validate_json(
                json.dumps(state["request_payload"]), strict=True
            )
            if str(request.project_id) != state["project_id"]:
                raise ValueError("EXPORT_PROJECT_MISMATCH")
            cursor = await self._prepare(request, thread_id=state["thread_id"])
        except ApplicationError as exc:
            return {"phase": "failed", "error_code": exc.code}
        except (ValueError, KeyError):
            return {"phase": "failed", "error_code": "EXPORT_REQUEST_INVALID"}
        return {
            "phase": "export_prepared",
            "export_cursor": cursor.model_dump(mode="json"),
            "plan_hash": cursor.plan_hash,
        }

    async def enqueue(self, state: Any) -> dict[str, Any]:
        cursor = CompleteExportCursorV2.model_validate_json(
            json.dumps(state["export_cursor"]), strict=True
        )
        try:
            cursor = await self._enqueue(cursor)
        except ApplicationError as exc:
            return {"phase": "failed", "error_code": exc.code}
        if not cursor.pending_steps:
            if cursor.bundle_artifact_id is None:
                return {"phase": "failed", "error_code": "EXPORT_INCOMPLETE"}
            return {
                "phase": "completed",
                "terminal_status": "succeeded",
                "export_cursor": cursor.model_dump(mode="json"),
            }
        return {
            "phase": "waiting_export_worker",
            "export_cursor": cursor.model_dump(mode="json"),
            "media_run_id": str(cursor.media_run_id),
            "pending_job_id": str(cursor.pending_job_id),
        }

    async def wait(self, state: Any) -> dict[str, Any]:
        resumed = interrupt(
            {
                "kind": "worker_job",
                "phase": "waiting_export_worker",
                "job_id": state["pending_job_id"],
            }
        )
        if isinstance(resumed, dict) and resumed == {"action": "cancel"}:
            await self._cancel(
                project_id=UUID(state["project_id"]),
                run_id=UUID(state["media_run_id"]),
                thread_id=state["thread_id"],
            )
            return {"phase": "cancelled", "terminal_status": "cancelled", "pending_job_id": None}
        try:
            payload = WorkerResumePayload.model_validate_json(json.dumps(resumed), strict=True)
        except ValueError:
            return {"phase": "failed", "error_code": "WORKER_RESUME_INVALID"}
        if payload.resume_event_id and payload.resume_event_id == state.get("last_resume_event_id"):
            return {"phase": "waiting_export_worker"}
        if (
            str(payload.job_id) != state["pending_job_id"]
            or str(payload.run_id) != state["media_run_id"]
            or payload.thread_id != state["thread_id"]
            or payload.run_type != "parent.export.v1"
        ):
            return {"phase": "failed", "error_code": "WORKER_RESUME_MISMATCH"}
        if payload.status != "succeeded":
            return {
                "phase": "failed",
                "error_code": payload.error_code or "WORKER_TERMINAL_FAILURE",
                "last_resume_event_id": payload.resume_event_id,
            }
        cursor = CompleteExportCursorV2.model_validate_json(
            json.dumps(state["export_cursor"]), strict=True
        )
        try:
            cursor = await self._collect(cursor, completed_job_id=payload.job_id)
        except ApplicationError as exc:
            return {
                "phase": "failed",
                "error_code": exc.code,
                "last_resume_event_id": payload.resume_event_id,
            }
        return {
            "phase": "export_step_collected",
            "export_cursor": cursor.model_dump(mode="json"),
            "pending_job_id": None,
            "last_resume_event_id": payload.resume_event_id,
            "artifact_refs": [
                *(str(a) for a in cursor.audio_artifact_ids),
                *([str(cursor.bundle_artifact_id)] if cursor.bundle_artifact_id else []),
            ],
        }
