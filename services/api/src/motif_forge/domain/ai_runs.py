"""Strict, replay-safe domain contracts for one finite AI generation run."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.agent.schemas import CompositionPlan
from motif_forge.domain.ir import DomainModel

AI_RUN_SCHEMA_VERSION = "ai-run.v1"
MAX_MODEL_REQUESTS = 3
PARENT_GRAPH_TOPOLOGY_VERSION = "motif-forge-parent.v2"
GENERATE_RUN_STATE_SCHEMA_VERSION = "generate-run-state.v1"


class AIRunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    MATERIALIZING = "materializing"
    WAITING_WORKER = "waiting_worker"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CostStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ModelRequestKind(StrEnum):
    INITIAL = "initial"
    TRANSPORT_RETRY = "transport_retry"
    SCHEMA_REPAIR = "schema_repair"
    STRATEGY_REPAIR = "strategy_repair"


class ModelRequestReservationStatus(StrEnum):
    RESERVED = "reserved"
    OBSERVED = "observed"


_TERMINAL = frozenset(
    {
        AIRunStatus.SUCCEEDED,
        AIRunStatus.REJECTED,
        AIRunStatus.FAILED,
        AIRunStatus.CANCELLED,
    }
)
_TRANSITIONS: dict[AIRunStatus, frozenset[AIRunStatus]] = {
    AIRunStatus.QUEUED: frozenset(
        {AIRunStatus.PLANNING, AIRunStatus.CANCELLED, AIRunStatus.FAILED}
    ),
    AIRunStatus.PLANNING: frozenset(
        {AIRunStatus.WAITING_APPROVAL, AIRunStatus.FAILED, AIRunStatus.CANCELLED}
    ),
    AIRunStatus.WAITING_APPROVAL: frozenset(
        {AIRunStatus.MATERIALIZING, AIRunStatus.REJECTED, AIRunStatus.CANCELLED}
    ),
    AIRunStatus.MATERIALIZING: frozenset(
        {AIRunStatus.WAITING_WORKER, AIRunStatus.FAILED, AIRunStatus.CANCELLED}
    ),
    AIRunStatus.WAITING_WORKER: frozenset(
        {AIRunStatus.SUCCEEDED, AIRunStatus.FAILED, AIRunStatus.CANCELLED}
    ),
    AIRunStatus.SUCCEEDED: frozenset(),
    AIRunStatus.REJECTED: frozenset(),
    AIRunStatus.FAILED: frozenset(),
    AIRunStatus.CANCELLED: frozenset(),
}
_ACTION_TRANSITIONS: dict[str, dict[AIRunStatus, AIRunStatus]] = {
    "cancel": {
        AIRunStatus.QUEUED: AIRunStatus.CANCELLED,
        AIRunStatus.PLANNING: AIRunStatus.CANCELLED,
        AIRunStatus.WAITING_APPROVAL: AIRunStatus.CANCELLED,
        AIRunStatus.MATERIALIZING: AIRunStatus.CANCELLED,
        AIRunStatus.WAITING_WORKER: AIRunStatus.CANCELLED,
    },
}
_SENSITIVE_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "prompt",
        "response",
        "api_key",
        "secret",
        "authorization",
        "password",
    }
)
_SAFE_USAGE_KEYS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    }
)


def canonical_plan_json_bytes(plan: CompositionPlan) -> bytes:
    """Use the project's stable canonical JSON rules for immutable model output."""

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalize(value[key]) for key in sorted(value)}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("canonical JSON cannot contain NaN or Infinity")
            rounded = round(value, 6)
            return 0.0 if rounded == 0.0 else rounded
        return value

    return json.dumps(
        normalize(plan.model_dump(mode="json", exclude_none=False)),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def composition_plan_content_hash(plan: CompositionPlan) -> str:
    return hashlib.sha256(canonical_plan_json_bytes(plan)).hexdigest()


def approval_assertion_hash(assertion: str) -> str:
    return hashlib.sha256(assertion.encode("utf-8")).hexdigest()


def validate_event_payload(payload: dict[str, object]) -> dict[str, object]:
    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized_key = key.casefold()
                if normalized_key not in _SAFE_USAGE_KEYS and (
                    any(part in normalized_key for part in _SENSITIVE_KEYS)
                    or normalized_key.endswith("_token")
                    or normalized_key == "token"
                ):
                    raise ValueError(
                        "AI run event payload cannot contain reasoning or secret-like fields"
                    )
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)

    visit(payload)
    return payload


class ModelCost(DomainModel):
    status: CostStatus
    amount_microusd: int | None = Field(default=None, ge=0)
    pricing_version: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_cost(self) -> Self:
        if self.status is CostStatus.KNOWN and (
            self.amount_microusd is None or self.pricing_version is None
        ):
            raise ValueError("known cost requires amount_microusd and pricing_version")
        if self.status is not CostStatus.KNOWN and (
            self.amount_microusd is not None or self.pricing_version is not None
        ):
            raise ValueError(
                "unknown or not_applicable cost must not carry an amount or pricing version"
            )
        return self


class AIRunApproval(DomainModel):
    approval_id: UUID
    run_id: UUID
    assertion_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: str = Field(min_length=1, max_length=24)
    actor_id: str = Field(min_length=1, max_length=160)
    expected_plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    interrupt_ref: str = Field(min_length=1, max_length=160)
    decided_at: datetime


class AIRun(DomainModel):
    run_id: UUID
    parent_run_id: UUID | None = None
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    graph_topology_version: str = Field(
        default=PARENT_GRAPH_TOPOLOGY_VERSION, min_length=1, max_length=80
    )
    state_schema_version: str = Field(
        default=GENERATE_RUN_STATE_SCHEMA_VERSION, min_length=1, max_length=80
    )
    brief: dict[str, object] | None = None
    status: AIRunStatus = AIRunStatus.QUEUED
    version: int = Field(default=0, ge=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)
    approval_assertion_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pending_plan_id: UUID | None = None
    pending_plan_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pending_interrupt_ref: str | None = Field(default=None, min_length=16, max_length=160)
    submitted_model_requests: int = Field(default=0, ge=0, le=MAX_MODEL_REQUESTS)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cost: ModelCost = Field(default_factory=lambda: ModelCost(status=CostStatus.UNKNOWN))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    terminal_at: datetime | None = None

    @model_validator(mode="after")
    def validate_terminal_state(self) -> Self:
        if (self.status in _TERMINAL) != (self.terminal_at is not None):
            raise ValueError("terminal status and terminal_at must be present together")
        return self

    def transition(self, status: AIRunStatus, *, now: datetime) -> AIRun:
        if status not in _TRANSITIONS[self.status]:
            raise ValueError(f"invalid AI run status transition: {self.status} -> {status}")
        return self.model_copy(
            update={
                "status": status,
                "version": self.version + 1,
                "updated_at": now,
                "terminal_at": now if status in _TERMINAL else None,
            }
        )

    def transition_for_action(self, action: str, *, now: datetime) -> AIRun:
        target = _ACTION_TRANSITIONS.get(action, {}).get(self.status)
        if target is None:
            raise ValueError(f"invalid AI run action: {action} from {self.status}")
        return self.transition(target, now=now)


class PersistedCompositionPlan(DomainModel):
    plan_id: UUID
    run_id: UUID
    plan: CompositionPlan
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    prompt_version: str = Field(min_length=1, max_length=80)
    schema_version: str = Field(min_length=1, max_length=80)
    style_pack_version: str = Field(min_length=1, max_length=80)
    fallback_reason: str | None = Field(default=None, max_length=240)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.content_hash != composition_plan_content_hash(self.plan):
            raise ValueError("content_hash must match canonical CompositionPlan")
        return self


class AIRunEvent(DomainModel):
    sequence: int = Field(ge=1)
    event_id: UUID
    run_id: UUID
    event_type: str = Field(min_length=1, max_length=80)
    phase: str = Field(min_length=1, max_length=80)
    payload: dict[str, object] = Field(default_factory=dict)
    dedupe_key: str | None = Field(default=None, min_length=1, max_length=240)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        validate_event_payload(self.payload)
        return self


class ModelRequestReservation(DomainModel):
    reservation_id: UUID
    run_id: UUID
    request_ordinal: int = Field(ge=1, le=MAX_MODEL_REQUESTS)
    kind: ModelRequestKind
    status: ModelRequestReservationStatus = ModelRequestReservationStatus.RESERVED
    provider_operation_id: str | None = Field(default=None, min_length=1, max_length=200)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observed_at: datetime | None = None
