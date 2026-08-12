"""Deterministic Agent error routing policy.

Infrastructure failures are classified from stable facts and codes.  The model is
never asked whether its own failure should be retried or hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ERROR_POLICY_VERSION = "agent-error-policy.v1"
ErrorRoute = Literal["repair", "fallback", "human", "terminal"]


@dataclass(frozen=True, slots=True)
class ErrorFacts:
    category: str
    code: str
    retryable: bool
    suggested_route: str
    repair_attempts: int
    model_calls_remaining: int


@dataclass(frozen=True, slots=True)
class ErrorDecision:
    route: ErrorRoute
    rule_id: str
    explanation_code: str
    policy_version: str = ERROR_POLICY_VERSION


def classify_agent_error(facts: ErrorFacts) -> ErrorDecision:
    """Return one conservative route using ordered, versioned rules."""

    if facts.code in {
        "DEEPSEEK_HTTP_401",
        "DEEPSEEK_HTTP_402",
        "DEEPSEEK_HTTP_403",
        "DEEPSEEK_API_KEY_MISSING",
        "DEEPSEEK_MODEL_UNSUPPORTED",
        "DEEPSEEK_BASE_URL_INVALID",
    }:
        return ErrorDecision("human", "ERR-001", "MODEL_CONFIGURATION_REQUIRES_HUMAN")

    if facts.category == "schema" and facts.repair_attempts < 1 and facts.model_calls_remaining > 0:
        return ErrorDecision("repair", "ERR-002", "BOUNDED_SCHEMA_REPAIR_AVAILABLE")

    if facts.category == "model_provider" and facts.retryable:
        # Provider HTTP retries are already exhausted.  Graph must not multiply
        # them; the safe composition-level recovery is an explicit template.
        return ErrorDecision("fallback", "ERR-003", "PROVIDER_RETRIES_EXHAUSTED")

    if facts.code in {
        "DEEPSEEK_OUTPUT_TRUNCATED",
        "DEEPSEEK_EMPTY_CONTENT",
        "DEEPSEEK_SCHEMA_INVALID",
        "DEEPSEEK_UNEXPECTED_TOOL_CALL",
    }:
        return ErrorDecision("fallback", "ERR-004", "MODEL_OUTPUT_UNUSABLE")

    if facts.category in {"input", "approval"}:
        return ErrorDecision("human", "ERR-005", "USER_INPUT_REQUIRED")

    if facts.suggested_route == "human":
        return ErrorDecision("human", "ERR-006", "PROVIDER_REQUESTED_HUMAN")

    return ErrorDecision("terminal", "ERR-999", "NO_SAFE_RECOVERY_ROUTE")
