from datetime import UTC, datetime
from uuid import uuid4

import pytest
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunEvent,
    AIRunStatus,
    CostStatus,
    ModelCost,
    approval_assertion_hash,
)
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


def test_ai_run_event_allows_token_counts_but_rejects_credentials() -> None:
    event = AIRunEvent(
        sequence=1,
        event_id=uuid4(),
        run_id=uuid4(),
        event_type="model.completed",
        phase="planning",
        payload={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    )
    assert event.payload["total_tokens"] == 14
    with pytest.raises(ValidationError):
        AIRunEvent(
            sequence=1,
            event_id=uuid4(),
            run_id=uuid4(),
            event_type="model.completed",
            phase="planning",
            payload={"access_token": "not-safe"},
        )


def test_ai_run_persists_graph_and_state_compatibility_versions() -> None:
    run = AIRun(
        run_id=uuid4(),
        project_id=uuid4(),
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        thread_id="generate-abc",
        graph_topology_version="motif-forge-graph.v1",
        state_schema_version="generate-run-state.v1",
    )
    assert run.graph_topology_version == "motif-forge-graph.v1"
    assert approval_assertion_hash("approved after review") != "approved after review"


def test_ai_run_action_transitions_are_finite() -> None:
    now = datetime.now(UTC)
    queued = AIRun(
        run_id=uuid4(),
        project_id=uuid4(),
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        thread_id="generate-abc",
    )
    assert queued.transition_for_action("cancel", now=now).status is AIRunStatus.CANCELLED
    with pytest.raises(ValueError):
        queued.transition_for_action("resume", now=now)
