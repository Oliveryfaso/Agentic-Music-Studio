from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agent.sample_data import valid_plan_payload
from fastapi.testclient import TestClient
from motif_forge.agent.schemas import CompositionPlan
from motif_forge.api.app import create_app
from motif_forge.application.ports import AIRunProgress, AIRunProjection
from motif_forge.config import Settings
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunStatus,
    PersistedCompositionPlan,
    composition_plan_content_hash,
)


def persisted_plan(run_id: UUID) -> PersistedCompositionPlan:
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    return PersistedCompositionPlan(
        plan_id=uuid4(), run_id=run_id, plan=plan,
        content_hash=composition_plan_content_hash(plan), provider="deepseek",
        model="deepseek-chat", prompt_version="planner.v1",
        schema_version="composition-plan.v1", style_pack_version="synth-ambient.v1",
        fallback_reason=None, created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


class FakeReplanTransaction:
    def __init__(self) -> None:
        self.parent = AIRun(
            run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
            thread_id=f"api-parent-{uuid4().hex}", status=AIRunStatus.WAITING_APPROVAL,
            version=1, brief={
                "title": "API parent", "purpose": "Review a calm plan",
                "style": "synth_ambient", "duration_seconds": 60,
                "moods": ["calm"],
            }, pending_plan_id=uuid4(), pending_plan_content_hash="a" * 64,
            pending_interrupt_ref="api-plan-interrupt",
        )
        self.plan = persisted_plan(self.parent.run_id)
        self.parent = self.parent.model_copy(update={
            "pending_plan_id": self.plan.plan_id,
            "pending_plan_content_hash": self.plan.content_hash,
        })
        self.child: AIRun | None = None

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    async def read_ai_run(self, run_id: UUID) -> AIRun:
        if self.child is not None and run_id == self.child.run_id:
            return self.child
        assert run_id == self.parent.run_id
        return self.parent

    async def read_ai_run_projection(self, run_id: UUID) -> AIRunProjection:
        assert run_id == self.parent.run_id
        return AIRunProjection(
            run=self.parent,
            plan=self.plan,
            progress=AIRunProgress(
                phase="waiting_approval",
                completed_export_steps=(),
                total_export_steps=7,
                latest_event_sequence=3,
                error_code=None,
            ),
        )

    async def replan_ai_run(self, **kwargs):  # type: ignore[no-untyped-def]
        if self.child is None:
            self.child = AIRun(
                run_id=kwargs["child_run_id"], parent_run_id=self.parent.run_id,
                project_id=self.parent.project_id, branch_id=self.parent.branch_id,
                base_revision_id=self.parent.base_revision_id,
                thread_id=kwargs["child_thread_id"], brief=kwargs["child_brief"],
                created_at=kwargs["now"], updated_at=kwargs["now"],
            )
        return self.child


class FakeReplanUOW:
    def __init__(self) -> None:
        self.transaction = FakeReplanTransaction()

    def __call__(self) -> FakeReplanTransaction:
        return self.transaction


def adjustment_body() -> dict[str, object]:
    return {
        "expected_version": 1,
        "expected_plan_hash": "",
        "adjustment": {
            "schema_version": "plan-adjustment.v1",
            "target_bpm": 88,
            "target_key": None,
            "sections": None,
            "instrumentation": None,
            "note": "Make the pacing slightly calmer.",
        },
    }


def test_get_run_exposes_the_strict_persisted_plan() -> None:
    uow = FakeReplanUOW()
    app = create_app(Settings(environment="test"), ai_run_uow_factory=uow)  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.get(f"/api/v1/runs/{uow.transaction.parent.run_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pending_plan_hash"] == uow.transaction.plan.content_hash
    assert data["plan"]["plan_id"] == str(uow.transaction.plan.plan_id)
    assert data["plan"]["content_hash"] == uow.transaction.plan.content_hash
    assert data["plan"]["hash_version"] == "composition-plan-hash.lossless-v2"
    assert data["plan"]["plan"] == valid_plan_payload()
    assert data["progress"] == {
        "phase": "waiting_approval",
        "completed_export_steps": [],
        "total_export_steps": 7,
        "latest_event_sequence": 3,
        "error_code": None,
    }
    assert "prompt" not in str(data["plan"])
    assert "reasoning" not in str(data["plan"])


def test_openapi_exposes_generated_run_and_event_contracts() -> None:
    app = create_app(
        Settings(environment="test"), ai_run_uow_factory=FakeReplanUOW()
    )  # type: ignore[arg-type]
    document = app.openapi()

    assert {"AIRunData", "AIRunEvent", "AIRunResponse", "RunProgressData"} <= set(
        document["components"]["schemas"]
    )
    read_schema = document["paths"]["/api/v1/runs/{run_id}"]["get"]["responses"]["200"]
    assert read_schema["content"]["application/json"]["schema"]["$ref"].endswith(
        "/AIRunResponse"
    )
    event_schema = document["paths"]["/api/v1/runs/{run_id}/events"]["get"]["responses"][
        "200"
    ]
    assert event_schema["content"]["text/event-stream"]["schema"]["$ref"].endswith(
        "/AIRunEvent"
    )


def test_replan_route_creates_and_replays_one_child_run() -> None:
    uow = FakeReplanUOW()
    body = adjustment_body()
    body["expected_plan_hash"] = uow.transaction.plan.content_hash
    app = create_app(Settings(environment="test"), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    url = f"/api/v1/runs/{uow.transaction.parent.run_id}/replan"

    with TestClient(app) as client:
        first = client.post(url, headers={"Idempotency-Key": "replan-http-key"}, json=body)
        replay = client.post(url, headers={"Idempotency-Key": "replan-http-key"}, json=body)

    assert first.status_code == replay.status_code == 202
    assert first.json()["data"]["run_id"] == replay.json()["data"]["run_id"]
    assert first.json()["data"]["parent_run_id"] == str(uow.transaction.parent.run_id)
    assert first.json()["data"]["status"] == "queued"
