"""Finite human audition nodes mounted in the production Parent Graph."""

from __future__ import annotations

import json
from typing import Any, Protocol

from langgraph.types import interrupt

from motif_forge.application.candidate_previews import CandidatePreviewCursor
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_preview import (
    PianoPrepared,
    PianoPreviewDecision,
    PianoPreviewRequest,
    PianoStep,
)
from motif_forge.application.previews import DecidePreviewResult
from motif_forge.domain.media_jobs import WorkerResumePayload


class PianoServices(Protocol):
    async def prepare(self, request: PianoPreviewRequest, *, thread_id: str) -> PianoPrepared: ...
    async def enqueue(
        self, prepared: PianoPrepared, *, step: PianoStep
    ) -> CandidatePreviewCursor: ...
    async def collect(
        self, prepared: PianoPrepared, cursor: CandidatePreviewCursor, *, step: PianoStep
    ) -> CandidatePreviewCursor: ...
    async def decide(
        self,
        prepared: PianoPrepared,
        decision: PianoPreviewDecision,
        cursor: CandidatePreviewCursor,
    ) -> DecidePreviewResult: ...
    async def cancel(self, prepared: PianoPrepared, cursor: CandidatePreviewCursor) -> None: ...


class PianoPreviewNodes:
    def __init__(self, service: PianoServices) -> None:
        self._service = service

    @staticmethod
    def prepared(state: Any) -> PianoPrepared:
        return PianoPrepared.model_validate_json(json.dumps(state["piano_data"]), strict=True)

    @staticmethod
    def cursor(state: Any) -> CandidatePreviewCursor:
        return CandidatePreviewCursor.model_validate_json(
            json.dumps(state["piano_cursor"]), strict=True
        )

    async def validate(self, state: Any) -> dict[str, Any]:
        try:
            request = PianoPreviewRequest.model_validate_json(
                json.dumps(state["request_payload"]), strict=True
            )
            if str(request.project_id) != state["project_id"]:
                raise ValueError("PIANO_PROJECT_MISMATCH")
            prepared = await self._service.prepare(request, thread_id=state["thread_id"])
        except ApplicationError as exc:
            return {"phase": "failed", "error_code": exc.code}
        except (ValueError, KeyError):
            return {"phase": "failed", "error_code": "PIANO_REQUEST_INVALID"}
        return {"phase": "piano_prepared", "piano_data": prepared.model_dump(mode="json")}

    async def enqueue(self, state: Any) -> dict[str, Any]:
        if state.get("piano_artifact_id"):
            return {"phase": "waiting_piano_approval", "pending_job_id": None}
        step: PianoStep = "piano" if state.get("piano_baseline_artifact_id") else "baseline"
        try:
            cursor = await self._service.enqueue(self.prepared(state), step=step)
        except ApplicationError as exc:
            return {"phase": "failed", "error_code": exc.code}
        return {
            "phase": "waiting_piano_worker",
            "piano_step": step,
            "piano_cursor": cursor.model_dump(mode="json"),
            "media_run_id": str(cursor.media_run_id),
            "pending_job_id": str(cursor.job_id),
        }

    async def wait(self, state: Any) -> dict[str, Any]:
        resumed = interrupt(
            {
                "kind": "worker_job",
                "phase": "waiting_piano_worker",
                "job_id": state["pending_job_id"],
            }
        )
        prepared, cursor = self.prepared(state), self.cursor(state)
        if isinstance(resumed, dict) and resumed == {"action": "cancel"}:
            await self._service.cancel(prepared, cursor)
            return {"phase": "cancelled", "terminal_status": "cancelled", "pending_job_id": None}
        try:
            payload = WorkerResumePayload.model_validate_json(json.dumps(resumed), strict=True)
        except ValueError:
            return {"phase": "failed", "error_code": "WORKER_RESUME_INVALID"}
        if payload.resume_event_id and payload.resume_event_id == state.get("last_resume_event_id"):
            return {"phase": "waiting_piano_worker"}
        if (
            str(payload.job_id) != str(cursor.job_id)
            or str(payload.run_id) != str(cursor.media_run_id)
            or payload.thread_id != prepared.thread_id
            or payload.run_type != "parent.piano_preview.v1"
        ):
            return {"phase": "failed", "error_code": "WORKER_RESUME_MISMATCH"}
        if payload.status != "succeeded":
            return {
                "phase": "failed",
                "error_code": payload.error_code or "WORKER_TERMINAL_FAILURE",
                "last_resume_event_id": payload.resume_event_id,
            }
        try:
            cursor = await self._service.collect(prepared, cursor, step=state["piano_step"])
        except ApplicationError as exc:
            return {"phase": "failed", "error_code": exc.code}
        field = (
            "piano_baseline_artifact_id"
            if state["piano_step"] == "baseline"
            else "piano_artifact_id"
        )
        return {
            "phase": "piano_step_collected",
            "piano_cursor": cursor.model_dump(mode="json"),
            field: str(cursor.preview_artifact_id),
            "pending_job_id": None,
            "last_resume_event_id": payload.resume_event_id,
        }

    async def approve(self, state: Any) -> dict[str, Any]:
        prepared = self.prepared(state)
        resumed = interrupt(
            {
                "kind": "piano_approval",
                "phase": "waiting_piano_approval",
                "candidate_content_hash": prepared.candidate_content_hash,
                "baseline_artifact_id": state["piano_baseline_artifact_id"],
                "piano_artifact_id": state["piano_artifact_id"],
            }
        )
        try:
            decision = PianoPreviewDecision.model_validate_json(json.dumps(resumed), strict=True)
            if decision.expected_candidate_content_hash != prepared.candidate_content_hash:
                return {
                    "phase": "waiting_piano_approval",
                    "error_code": "PIANO_CANDIDATE_HASH_MISMATCH",
                }
            result = await self._service.decide(prepared, decision, self.cursor(state))
        except ApplicationError as exc:
            return {"phase": "failed", "error_code": exc.code}
        except ValueError:
            return {"phase": "waiting_piano_approval", "error_code": "PIANO_DECISION_INVALID"}
        approved = decision.action == "approve"
        return {
            "phase": "completed" if approved else "rejected",
            "terminal_status": "succeeded" if approved else "rejected",
            "error_code": None,
            "piano_revision_id": str(result.revision_id) if result.revision_id else None,
            "piano_decision": decision.model_dump(mode="json"),
        }
