"""Composition planner port and deterministic test implementation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan


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
class PlannerResponse:
    """Provider-neutral structured result; raw reasoning is deliberately absent."""

    plan_payload: Mapping[str, Any]
    usage: PlannerUsage = PlannerUsage()
    provider: str = "fake"
    model: str = "deterministic"
    prompt_version: str = "composition-planner.v1"
    schema_version: str = "composition-plan.v1"


class CompositionPlanner(Protocol):
    async def create_plan(self, brief: CompositionBrief) -> PlannerResponse:
        """Create a bounded structured plan without performing side effects."""


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


@dataclass(frozen=True, slots=True)
class StaticCompositionPlanner:
    """Injectable fake used by unit tests, local demos, and eval baselines."""

    plan: CompositionPlan | Mapping[str, Any]
    failure: PlannerError | None = None

    async def create_plan(self, brief: CompositionBrief) -> PlannerResponse:
        del brief
        if self.failure is not None:
            raise self.failure
        payload = (
            self.plan.model_dump(mode="json")
            if isinstance(self.plan, CompositionPlan)
            else self.plan
        )
        return PlannerResponse(plan_payload=payload)
