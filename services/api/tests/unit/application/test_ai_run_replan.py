from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from motif_forge.agent.schemas import CompositionBrief, PlanAdjustment
from motif_forge.application.ai_runs import ReplanAIRun, ReplanAIRunRequest, derive_replan_brief
from motif_forge.domain.ai_runs import AIRun, AIRunStatus


def parent_brief() -> CompositionBrief:
    return CompositionBrief.model_validate_json(json.dumps({
        "title": "Parent",
        "purpose": "A calm portfolio underscore",
        "style": "synth_ambient",
        "duration_seconds": 60,
        "meter": "4/4",
        "moods": ["calm"],
        "preferred_instruments": ["Old Pad"],
        "soft_preferences": ["Keep the mix spacious"],
    }), strict=True)


def adjustment() -> PlanAdjustment:
    return PlanAdjustment.model_validate_json(json.dumps({
        "schema_version": "plan-adjustment.v1",
        "target_bpm": 96,
        "target_key": "E minor",
        "sections": [
            {"name": "Arrival", "bars": 8, "energy": 0.25},
            {"name": "Motion", "bars": 16, "energy": 0.75},
        ],
        "instrumentation": [
            {"name": "Glass Pad", "role": "harmony"},
            {"name": "Muted Pulse", "role": "rhythm"},
        ],
        "note": "Avoid an abrupt transition.",
    }), strict=True)


def waiting_parent() -> AIRun:
    return AIRun(
        run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
        thread_id=f"parent-{uuid4().hex}", brief=parent_brief().model_dump(mode="json"),
        status=AIRunStatus.WAITING_APPROVAL, version=1, pending_plan_id=uuid4(),
        pending_plan_content_hash="a" * 64,
        pending_interrupt_ref="plan-interrupt-ref",
    )


class FakeReplanTransaction:
    def __init__(self, parent: AIRun) -> None:
        self.parent = parent
        self.child: AIRun | None = None
        self.calls = 0

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    async def read_ai_run(self, run_id: UUID) -> AIRun:
        assert run_id == self.parent.run_id
        return self.parent

    async def replan_ai_run(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.child is None:
            self.child = AIRun(
                run_id=kwargs["child_run_id"], parent_run_id=self.parent.run_id,
                project_id=self.parent.project_id, branch_id=self.parent.branch_id,
                base_revision_id=self.parent.base_revision_id,
                thread_id=kwargs["child_thread_id"], brief=kwargs["child_brief"],
                max_model_requests=self.parent.max_model_requests,
                max_total_tokens=self.parent.max_total_tokens,
                created_at=kwargs["now"], updated_at=kwargs["now"],
            )
        return self.child


class FakeReplanUOW:
    def __init__(self, parent: AIRun) -> None:
        self.transaction = FakeReplanTransaction(parent)

    def __call__(self) -> FakeReplanTransaction:
        return self.transaction


def test_adjustment_deterministically_derives_a_strict_child_brief() -> None:
    derived = derive_replan_brief(parent_brief(), adjustment())

    assert derived.target_bpm == 96
    assert derived.target_key == "E minor"
    assert derived.preferred_instruments == ("Glass Pad", "Muted Pulse")
    normalized = " ".join(derived.soft_preferences)
    assert "Arrival" in normalized and "energy=0.25" in normalized
    assert "Glass Pad" in normalized and "role=harmony" in normalized
    assert "Avoid an abrupt transition." in normalized


@pytest.mark.asyncio
async def test_replan_creates_one_child_without_mutating_the_parent() -> None:
    parent = waiting_parent()
    before = parent.model_dump(mode="json")
    uow = FakeReplanUOW(parent)
    request = ReplanAIRunRequest(
        run_id=parent.run_id, expected_version=1, expected_plan_hash="a" * 64,
        adjustment=adjustment(), idempotency_key="replan-key-001",
    )
    ids = iter((UUID(int=101), UUID(int=102), UUID(int=103), UUID(int=104)))
    service = ReplanAIRun(
        uow, id_factory=lambda: next(ids),
        clock=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )  # type: ignore[arg-type]

    child = await service(request)

    assert child.parent_run_id == parent.run_id
    assert child.project_id == parent.project_id
    assert child.branch_id == parent.branch_id
    assert child.base_revision_id == parent.base_revision_id
    assert child.status is AIRunStatus.QUEUED
    assert CompositionBrief.model_validate_json(
        json.dumps(child.brief), strict=True
    ).target_bpm == 96
    assert parent.model_dump(mode="json") == before
    assert uow.transaction.calls == 1
