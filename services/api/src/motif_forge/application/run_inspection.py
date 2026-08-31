"""Safe, read-only Parent Graph inspection models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from motif_forge.application.errors import ApplicationError

type SafeValue = str | int | bool | None
SAFE_EVENT_FIELDS = frozenset({
    "action", "actor_id", "artifact_id", "candidate_id", "completed_step",
    "decision", "error_code", "fallback_reason", "job_id", "max_model_requests",
    "max_total_tokens", "model", "phase", "plan_id", "preview_id", "provider",
    "request_kind", "revision_id", "run_type", "status", "target_status",
})


class InspectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InspectionRunSummary(InspectionModel):
    run_id: UUID
    project_id: UUID
    thread_id: str
    run_type: str
    status: str
    version: int = Field(ge=0)
    revision_id: UUID | None
    bundle_id: UUID | None
    error_code: str | None


class RunVersionSummary(InspectionModel):
    graph_topology_version: str
    state_schema_version: str


class RunUsageSummary(InspectionModel):
    submitted_model_requests: int = Field(ge=0)
    max_model_requests: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_status: str
    cost_status: str
    cost_amount_microusd: int | None = Field(default=None, ge=0)


class InspectionEvent(InspectionModel):
    sequence: int = Field(ge=1)
    event_type: str
    phase: str
    created_at: datetime
    summary: dict[str, SafeValue]


class DecisionSummary(InspectionModel):
    kind: Literal["plan", "edit"]
    decision: str
    actor_id: str
    decided_at: datetime


class InspectionJob(InspectionModel):
    job_id: UUID
    job_type: str
    status: str
    attempts: int = Field(ge=0)
    error_code: str | None


class InspectionArtifact(InspectionModel):
    artifact_id: UUID
    source_job_id: UUID
    quality_profile: str
    availability: str
    byte_size: int = Field(ge=0)


class RecoverySummary(InspectionModel):
    resume_events: int = Field(ge=0)
    replay_events: int = Field(ge=0)
    retry_events: int = Field(ge=0)
    cancel_events: int = Field(ge=0)
    terminal_outcome: str | None


class RunInspectionFacts(InspectionModel):
    run: InspectionRunSummary
    versions: RunVersionSummary
    usage: RunUsageSummary
    timeline: tuple[InspectionEvent, ...] = Field(max_length=200)
    timeline_truncated: bool
    decisions: tuple[DecisionSummary, ...]
    jobs: tuple[InspectionJob, ...]
    artifacts: tuple[InspectionArtifact, ...]
    recovery: RecoverySummary

    @property
    def run_id(self) -> UUID:
        return self.run.run_id


class RunInspectionStore(Protocol):
    async def read_run_inspection(self, run_id: UUID) -> RunInspectionFacts | None: ...


def safe_event_summary(
    event_type: str, payload: Mapping[str, object]
) -> dict[str, SafeValue]:
    del event_type
    return {
        key: value
        for key, value in sorted(payload.items())
        if key in SAFE_EVENT_FIELDS and isinstance(value, (str, int, bool, type(None)))
    }


class ReadAIRunInspection:
    def __init__(self, store: RunInspectionStore) -> None:
        self._store = store

    async def __call__(self, run_id: UUID) -> RunInspectionFacts:
        result = await self._store.read_run_inspection(run_id)
        if result is None:
            raise ApplicationError("AI_RUN_NOT_FOUND", "the AI Run does not exist")
        return result
