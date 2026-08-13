from datetime import UTC, datetime
from uuid import uuid4

import pytest
from motif_forge.domain.ai_runs import AIRun, AIRunEvent, AIRunStatus, CostStatus, ModelCost
from pydantic import ValidationError


def test_ai_run_rejects_terminal_status_without_terminal_timestamp() -> None:
    with pytest.raises(ValidationError):
        AIRun(
            run_id=uuid4(),
            project_id=uuid4(),
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            thread_id="generate-abc",
            status=AIRunStatus.SUCCEEDED,
            terminal_at=None,
        )


def test_unknown_cost_is_not_serialized_as_zero() -> None:
    cost = ModelCost(status=CostStatus.UNKNOWN)
    assert cost.amount_microusd is None
    assert cost.pricing_version is None


def test_terminal_status_requires_timestamp_and_non_terminal_forbids_it() -> None:
    now = datetime.now(UTC)
    assert (
        AIRun(
            run_id=uuid4(),
            project_id=uuid4(),
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            thread_id="generate-abc",
            status=AIRunStatus.CANCELLED,
            terminal_at=now,
        ).terminal_at
        == now
    )
    with pytest.raises(ValidationError):
        AIRun(
            run_id=uuid4(),
            project_id=uuid4(),
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            thread_id="generate-abc",
            terminal_at=now,
        )


def test_ai_run_event_rejects_raw_reasoning_and_secret_like_fields() -> None:
    with pytest.raises(ValidationError):
        AIRunEvent(
            sequence=1,
            event_id=uuid4(),
            run_id=uuid4(),
            event_type="planning",
            phase="planning",
            payload={"reasoning_content": "private chain"},
        )
