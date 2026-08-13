"""Composition planner port and deterministic test implementation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.domain.ai_runs import ModelRequestKind, ModelRequestReservation


@dataclass(frozen=True, slots=True)
class PlannerUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    reasoning_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "prompt_cache_hit_tokens": self.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": self.prompt_cache_miss_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True, slots=True)
class ModelBudgetSnapshot:
    """Truthful persisted model spend observed for one finite AI Run."""

    submitted_requests: int
    total_tokens: int
    max_requests: int = 3
    max_total_tokens: int = 12_000


class ProviderBudgetLedger(Protocol):
    """Persistent budget boundary invoked around every provider submission."""

    async def reserve_request(
        self, *, run_id: UUID, kind: ModelRequestKind
    ) -> ModelRequestReservation:
        """Atomically reserve one upstream request before network I/O."""

    async def record_usage(
        self, *, reservation_id: UUID, usage: PlannerUsage
    ) -> ModelBudgetSnapshot:
        """Persist provider-reported usage and return the aggregate Run budget."""


@dataclass(frozen=True, slots=True)
class PlannerResponse:
    """Provider-neutral structured result; raw reasoning is deliberately absent."""

    plan_payload: Mapping[str, Any]
    usage: PlannerUsage = PlannerUsage()
    provider: str = "fake"
    model: str = "deterministic"
    prompt_version: str = "composition-planner.v1"
    schema_version: str = "composition-plan.v1"
    model_calls: int = 1
    operation_id: str | None = None


class CompositionPlanner(Protocol):
    async def create_plan(
        self, brief: CompositionBrief, *, allow_schema_repair: bool = True
    ) -> PlannerResponse:
        """Create a bounded structured plan without performing side effects."""

    async def repair_plan(
        self,
        brief: CompositionBrief,
        *,
        invalid_payload: Mapping[str, Any],
        validation_issues: tuple[str, ...],
    ) -> PlannerResponse:
        """Make one bounded repair attempt from safe deterministic validation issues."""


class PlannerError(RuntimeError):
    """Safe provider-neutral planner failure."""

    def __init__(
        self,
        code: str,
        safe_summary: str,
        *,
        category: str = "model_provider",
        retryable: bool = False,
        suggested_route: str = "terminal",
    ) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary
        self.category = category
        self.retryable = retryable
        self.suggested_route = suggested_route


class ProviderBudgetExceeded(PlannerError):
    """Typed budget stop that the planning graph routes to fallback."""

    def __init__(self, code: str, safe_summary: str, snapshot: ModelBudgetSnapshot | None) -> None:
        super().__init__(
            code,
            safe_summary,
            category="model_provider",
            retryable=False,
            suggested_route="fallback",
        )
        self.snapshot = snapshot

    @classmethod
    def requests(cls, snapshot: ModelBudgetSnapshot | None = None) -> ProviderBudgetExceeded:
        return cls(
            "MODEL_REQUEST_BUDGET_EXHAUSTED",
            "The AI Run has exhausted its persisted model request budget.",
            snapshot,
        )

    @classmethod
    def tokens(cls, snapshot: ModelBudgetSnapshot) -> ProviderBudgetExceeded:
        return cls(
            "MODEL_TOKEN_BUDGET_EXHAUSTED",
            "The AI Run has exhausted its persisted model token budget.",
            snapshot,
        )


class PersistentProviderBudgetLedger:
    """Adapter from provider calls to Task 1's PostgreSQL-backed AI Run ledger."""

    def __init__(
        self,
        uow_factory: Any,
        *,
        run_id: UUID,
        max_requests: int = 3,
        max_total_tokens: int = 12_000,
    ):
        from motif_forge.application.ai_runs import (
            ReadAIRun,
            RecordModelUsage,
            ReserveModelRequest,
        )

        self._reserve = ReserveModelRequest(uow_factory)
        self._record = RecordModelUsage(uow_factory)
        self._read = ReadAIRun(uow_factory)
        self._run_id = run_id
        self._max_requests = max_requests
        self._max_total_tokens = max_total_tokens

    async def reserve_request(
        self, *, run_id: UUID, kind: ModelRequestKind
    ) -> ModelRequestReservation:
        from motif_forge.application.ai_runs import ModelRequestBudgetError

        if run_id != self._run_id:
            raise PlannerError(
                "MODEL_RUN_CONTEXT_MISMATCH",
                "The model request does not belong to this AI Run budget.",
                category="internal",
                retryable=False,
                suggested_route="terminal",
            )
        snapshot = await self._snapshot()
        if snapshot.total_tokens >= snapshot.max_total_tokens:
            raise ProviderBudgetExceeded.tokens(snapshot)
        try:
            reservation = await self._reserve(run_id=run_id, kind=kind)
        except ModelRequestBudgetError as exc:
            raise ProviderBudgetExceeded.requests(await self._snapshot()) from exc
        return reservation

    async def record_usage(
        self, *, reservation_id: UUID, usage: PlannerUsage
    ) -> ModelBudgetSnapshot:
        await self._record(
            run_id=self._run_id,
            reservation_id=reservation_id,
            provider_operation_id=f"provider-reservation:{reservation_id}",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
        snapshot = await self._snapshot()
        if snapshot.total_tokens > snapshot.max_total_tokens:
            raise ProviderBudgetExceeded.tokens(snapshot)
        return snapshot

    async def _snapshot(self) -> ModelBudgetSnapshot:
        run = await self._read(self._run_id)
        return ModelBudgetSnapshot(
            submitted_requests=run.submitted_model_requests,
            total_tokens=run.prompt_tokens + run.completion_tokens,
            max_requests=self._max_requests,
            max_total_tokens=self._max_total_tokens,
        )


@dataclass(frozen=True, slots=True)
class StaticCompositionPlanner:
    """Injectable fake used by unit tests, local demos, and eval baselines."""

    plan: CompositionPlan | Mapping[str, Any]
    failure: PlannerError | None = None
    repaired_plan: CompositionPlan | Mapping[str, Any] | None = None

    async def create_plan(
        self, brief: CompositionBrief, *, allow_schema_repair: bool = True
    ) -> PlannerResponse:
        del brief, allow_schema_repair
        if self.failure is not None:
            raise self.failure
        payload = (
            self.plan.model_dump(mode="json")
            if isinstance(self.plan, CompositionPlan)
            else self.plan
        )
        return PlannerResponse(plan_payload=payload)

    async def repair_plan(
        self,
        brief: CompositionBrief,
        *,
        invalid_payload: Mapping[str, Any],
        validation_issues: tuple[str, ...],
    ) -> PlannerResponse:
        del brief, invalid_payload, validation_issues
        if self.failure is not None:
            raise self.failure
        candidate = self.repaired_plan if self.repaired_plan is not None else self.plan
        payload = (
            candidate.model_dump(mode="json")
            if isinstance(candidate, CompositionPlan)
            else candidate
        )
        return PlannerResponse(plan_payload=payload)
