
import pytest
from motif_forge.application.ai_runs import ModelRequestBudgetError, model_request_allowed
from motif_forge.domain.ai_runs import ModelRequestKind


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
