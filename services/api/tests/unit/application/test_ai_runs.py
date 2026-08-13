import pytest
from motif_forge.application.ai_runs import (
    ModelRequestBudgetError,
    ModelUsageFactError,
    model_request_allowed,
    validate_model_usage_facts,
)
from motif_forge.domain.ai_runs import AIRunStatus, ModelRequestKind, ModelUsageStatus


def test_model_request_budget_refuses_fourth_upstream_request() -> None:
    with pytest.raises(ModelRequestBudgetError):
        model_request_allowed(
            submitted_model_requests=3,
            prior_request_kinds=(ModelRequestKind.INITIAL,) * 3,
            requested_kind=ModelRequestKind.TRANSPORT_RETRY,
        )


def test_model_request_budget_allows_only_one_shared_repair() -> None:
    with pytest.raises(ModelRequestBudgetError):
        model_request_allowed(
            submitted_model_requests=1,
            prior_request_kinds=(ModelRequestKind.SCHEMA_REPAIR,),
            requested_kind=ModelRequestKind.STRATEGY_REPAIR,
        )


def test_terminal_run_cannot_reserve_and_usage_facts_must_be_nonnegative() -> None:
    with pytest.raises(ModelRequestBudgetError):
        model_request_allowed(
            submitted_model_requests=0,
            prior_request_kinds=(),
            requested_kind=ModelRequestKind.INITIAL,
            run_status=AIRunStatus.CANCELLED,
        )
    with pytest.raises(ModelUsageFactError):
        validate_model_usage_facts(
            usage_status=ModelUsageStatus.PARTIAL,
            prompt_tokens=-1,
            completion_tokens=0,
            total_tokens=0,
            prompt_cache_hit_tokens=None,
            prompt_cache_miss_tokens=None,
            reasoning_tokens=None,
        )
