"""Secret-safe trace and usage records used by Graph nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from motif_forge.agent.planner import PlannerResponse


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    operation_id: str
    run_id: str
    thread_id: str
    node: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    thinking_mode: Literal["enabled", "disabled"]
    response: PlannerResponse | None
    status: Literal["succeeded", "failed"]
    error_code: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TelemetryRecorder(Protocol):
    async def record_model_call(self, record: ModelCallRecord) -> None:
        """Persist one logical provider operation idempotently."""


class NullTelemetryRecorder:
    async def record_model_call(self, record: ModelCallRecord) -> None:
        del record


@dataclass(frozen=True, slots=True)
class UsageRecord:
    operation_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_microusd: int | None
    cost_status: Literal["known", "unknown", "not_applicable"] = "unknown"
    pricing_version: str | None = None
