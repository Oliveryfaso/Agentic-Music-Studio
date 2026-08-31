from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.run_inspection import (
    InspectionEvent,
    InspectionRunSummary,
    ReadAIRunInspection,
    RecoverySummary,
    RunInspectionFacts,
    RunUsageSummary,
    RunVersionSummary,
    safe_event_summary,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


class FakeInspectionStore:
    facts: RunInspectionFacts | None = None

    async def read_run_inspection(self, run_id: UUID) -> RunInspectionFacts | None:
        return self.facts if self.facts and self.facts.run_id == run_id else None


def facts() -> RunInspectionFacts:
    return RunInspectionFacts(
        run=InspectionRunSummary(
            run_id=uid(1), project_id=uid(2), thread_id="thread-generate-1",
            run_type="generate", status="succeeded",
            version=5, revision_id=uid(3), bundle_id=uid(4), error_code=None,
        ),
        versions=RunVersionSummary(
            graph_topology_version="motif-forge-parent.v2",
            state_schema_version="parent-state.v2",
        ),
        usage=RunUsageSummary(
            submitted_model_requests=0, max_model_requests=3, max_total_tokens=12_000,
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            usage_status="known", cost_status="known", cost_amount_microusd=0,
        ),
        timeline=(InspectionEvent(
            sequence=1, event_type="ai_run.created", phase="queued",
            created_at=datetime(2026, 8, 25, tzinfo=UTC), summary={"run_type": "generate"},
        ),),
        timeline_truncated=False, decisions=(), jobs=(), artifacts=(),
        recovery=RecoverySummary(
            resume_events=0, replay_events=0, retry_events=0, cancel_events=0,
            terminal_outcome="succeeded",
        ),
    )


def test_safe_event_summary_drops_secrets_paths_prompts_and_unknown_fields() -> None:
    assert safe_event_summary("approval.recorded", {
        "decision": "approve", "actor_id": "local-user", "phase": "waiting_approval",
        "approval_assertion": "secret", "storage_key": "/private/data",
        "prompt": "hidden", "unknown": "drop-me", "nested": {"secret": True},
    }) == {"actor_id": "local-user", "decision": "approve", "phase": "waiting_approval"}


@pytest.mark.asyncio
async def test_inspection_returns_persisted_facts_and_missing_run_is_stable() -> None:
    store = FakeInspectionStore()
    store.facts = facts()

    assert await ReadAIRunInspection(store)(uid(1)) == store.facts
    assert store.facts.run.thread_id == "thread-generate-1"
    with pytest.raises(ApplicationError) as captured:
        await ReadAIRunInspection(store)(uid(99))
    assert captured.value.code == "AI_RUN_NOT_FOUND"
