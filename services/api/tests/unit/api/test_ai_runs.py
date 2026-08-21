from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from motif_forge.api.app import create_app
from motif_forge.application.errors import IdempotencyKeyReusedError
from motif_forge.application.ports import AIRunCandidateProjection, AIRunProjection, IdempotencyHit
from motif_forge.config import Settings
from motif_forge.domain.ai_runs import AIRun, AIRunApproval, AIRunStatus


class FakeAIRunTransaction:
    def __init__(self) -> None:
        self.run: AIRun | None = None
        self.outbox_creates = 0
        self.action_hits: dict[tuple[str, str], IdempotencyHit] = {}
        self.approval: AIRunApproval | None = None
        self.projection: AIRunProjection | None = None
        self.child: AIRun | None = None
        self.selection: dict[str, object] | None = None

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    async def get_ai_run_idempotency(self, *, project_id, key):  # type: ignore[no-untyped-def]
        from motif_forge.application._hashing import request_hash
        from motif_forge.application.ports import IdempotencyHit

        if self.run is None or self.run.project_id != project_id or self.run.idempotency_key != key:
            return None
        return IdempotencyHit(
            resource_id=self.run.run_id,
            request_hash=request_hash({
                "schema": "ai-run.create.v1",
                "project_id": str(self.run.project_id), "branch_id": str(self.run.branch_id),
                "base_revision_id": str(self.run.base_revision_id),
                "thread_id": self.run.thread_id, "brief": self.run.brief,
                "max_model_requests": self.run.max_model_requests,
                "max_total_tokens": self.run.max_total_tokens,
                "graph_topology_version": self.run.graph_topology_version,
                "state_schema_version": self.run.state_schema_version,
            }),
            result_payload={"run_id": str(self.run.run_id)},
        )

    async def create_ai_run(self, *, run, created_event, outbox_event_id, request_hash):  # type: ignore[no-untyped-def]
        del created_event, outbox_event_id, request_hash
        self.run = run
        self.outbox_creates += 1

    async def read_ai_run(self, run_id: UUID) -> AIRun:
        assert self.run is not None and self.run.run_id == run_id
        return self.run

    async def read_ai_run_projection(self, run_id: UUID) -> AIRunProjection:
        if self.projection is not None:
            return self.projection
        return AIRunProjection(run=await self.read_ai_run(run_id))

    async def get_ai_run_action_idempotency(
        self, *, parent_run_id: UUID, action: str, key: str
    ) -> IdempotencyHit | None:
        del parent_run_id
        return self.action_hits.get((action, key))

    async def read_ai_run_approval(self, run_id: UUID) -> AIRunApproval | None:
        del run_id
        return self.approval

    async def record_idempotent_ai_run_approval(self, **kwargs):  # type: ignore[no-untyped-def]
        key = ("resume", kwargs["idempotency_key"])
        prior = self.action_hits.get(key)
        if prior is not None:
            if prior.request_hash != kwargs["request_hash"]:
                raise IdempotencyKeyReusedError
            assert self.approval is not None
            return self.approval
        self.approval = kwargs["approval"]
        assert self.run is not None
        self.run = self.run.transition(AIRunStatus.MATERIALIZING, now=datetime.now(UTC))
        self.action_hits[key] = IdempotencyHit(
            resource_id=self.run.run_id, request_hash=kwargs["request_hash"],
            result_payload={"run_id": str(self.run.run_id)},
        )
        return self.approval

    async def record_idempotent_candidate_selection(self, **kwargs):  # type: ignore[no-untyped-def]
        key = ("select_candidate", kwargs["idempotency_key"])
        prior = self.action_hits.get(key)
        if prior is not None:
            if prior.request_hash != kwargs["request_hash"]:
                raise IdempotencyKeyReusedError
            return
        assert self.run is not None
        self.selection = kwargs
        self.action_hits[key] = IdempotencyHit(
            resource_id=self.run.run_id,
            request_hash=kwargs["request_hash"],
            result_payload={"run_id": str(self.run.run_id)},
        )

    async def request_ai_run_action(self, **kwargs):  # type: ignore[no-untyped-def]
        key = (kwargs["action"], kwargs["idempotency_key"])
        if key in self.action_hits:
            assert self.run is not None
            return self.run
        assert self.run is not None
        self.run = self.run.transition_for_action(kwargs["action"], now=kwargs["now"])
        self.action_hits[key] = IdempotencyHit(
            resource_id=self.run.run_id, request_hash="cancel", result_payload={},
        )
        return self.run

    async def retry_ai_run(self, **kwargs):  # type: ignore[no-untyped-def]
        key = ("retry", kwargs["idempotency_key"])
        if key in self.action_hits:
            assert self.child is not None
            return self.child
        assert self.run is not None
        self.child = self.run.model_copy(update={
            "run_id": kwargs["child_run_id"], "parent_run_id": self.run.run_id,
            "thread_id": kwargs["child_thread_id"], "status": AIRunStatus.QUEUED,
            "version": 0, "terminal_at": None,
        })
        self.action_hits[key] = IdempotencyHit(
            resource_id=self.child.run_id, request_hash=kwargs["request_hash"],
            result_payload={},
        )
        return self.child


class FakeAIRunUOW:
    def __init__(self) -> None:
        self.transaction = FakeAIRunTransaction()

    def __call__(self) -> FakeAIRunTransaction:
        return self.transaction


def test_create_ai_run_is_async_safe_and_forbids_runtime_internals() -> None:
    uow = FakeAIRunUOW()
    app = create_app(Settings.for_test(), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    body = {
        "branch_id": str(uuid4()),
        "base_revision_id": str(uuid4()),
        "max_model_requests": 1,
        "max_total_tokens": 12_000,
        "brief": {
            "title": "Safe API", "purpose": "Generate a calm underscore",
            "style": "synth_ambient", "duration_seconds": 60, "moods": ("calm",),
            "meter": "4/4",
        },
    }
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/projects/{uuid4()}/ai-runs",
            headers={"Idempotency-Key": "generate-safe-1"}, json=body,
        )
        assert response.status_code == 202
        assert response.json()["data"]["status"] == "queued"
        assert response.json()["data"]["max_model_requests"] == 1
        assert uow.transaction.run is not None
        assert uow.transaction.run.max_model_requests == 1
        assert uow.transaction.run.max_total_tokens == 12_000
        assert uow.transaction.outbox_creates == 1
        replay = client.post(
            response.request.url,
            headers={"Idempotency-Key": "generate-safe-1"}, json=body,
        )
        assert replay.status_code == 202
        assert replay.json()["data"]["run_id"] == response.json()["data"]["run_id"]
        assert uow.transaction.outbox_creates == 1
        forbidden = client.post(
            f"/api/v1/projects/{uuid4()}/ai-runs",
            headers={"Idempotency-Key": "generate-safe-2"},
            json={**body, "model": "deepseek", "node_name": "planner"},
        )
        assert forbidden.status_code == 422
        assert uow.transaction.outbox_creates == 1


def test_create_rejects_unsupported_style_and_meter_before_persistence() -> None:
    uow = FakeAIRunUOW()
    app = create_app(Settings.for_test(), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    with TestClient(app) as client:
        for brief in (
            {"title": "Bad", "purpose": "Bad style", "style": "metal",
             "duration_seconds": 60, "moods": ["calm"]},
            {"title": "Bad", "purpose": "Bad meter", "style": "synth_ambient",
             "duration_seconds": 60, "moods": ["calm"], "meter": "7/8"},
        ):
            response = client.post(
                f"/api/v1/projects/{uuid4()}/ai-runs",
                headers={"Idempotency-Key": f"invalid-{uuid4().hex}"},
                json={"branch_id": str(uuid4()), "base_revision_id": str(uuid4()),
                      "brief": brief},
            )
            assert response.status_code == 422
    assert uow.transaction.run is None
    assert uow.transaction.outbox_creates == 0


def test_resume_exact_replay_and_changed_request_conflict() -> None:
    uow = FakeAIRunUOW()
    plan_hash = "a" * 64
    uow.transaction.run = AIRun(
        run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
        thread_id="resume-http", status=AIRunStatus.WAITING_APPROVAL, version=1,
        pending_plan_id=uuid4(), pending_plan_content_hash=plan_hash,
        pending_interrupt_ref="pending-plan-interrupt-http",
    )
    app = create_app(Settings.for_test(), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    body = {
        "expected_version": 1, "expected_plan_hash": plan_hash,
        "actor_id": "human-a", "approval_assertion": "I approve this exact plan.",
        "decision": "approve", "note": "reviewed",
    }
    url = f"/api/v1/runs/{uow.transaction.run.run_id}/resume"
    with TestClient(app) as client:
        first = client.post(url, headers={"Idempotency-Key": "resume-http-key"}, json=body)
        replay = client.post(url, headers={"Idempotency-Key": "resume-http-key"}, json=body)
        assert first.status_code == replay.status_code == 200
        assert first.json()["data"] == replay.json()["data"]
        for field, value in (
            ("actor_id", "human-b"), ("approval_assertion", "I changed this assertion."),
            ("decision", "reject"), ("expected_plan_hash", "b" * 64),
            ("note", "changed"),
        ):
            conflict = client.post(
                url, headers={"Idempotency-Key": "resume-http-key"},
                json={**body, field: value},
            )
            assert conflict.status_code == 409


def test_get_projection_cancel_replay_and_retry_child_replay() -> None:
    uow = FakeAIRunUOW()
    run = AIRun(
        run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
        thread_id="actions-http",
    )
    uow.transaction.run = run
    uow.transaction.projection = AIRunProjection(
        run=run, revision_id=uuid4(), bundle_id=uuid4(),
        fallback_reason="provider unavailable", error_code="SAFE_FAILURE",
    )
    app = create_app(Settings.for_test(), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    with TestClient(app) as client:
        read = client.get(f"/api/v1/runs/{run.run_id}")
        assert read.status_code == 200
        assert read.json()["data"] | {
            "revision_id": str(uow.transaction.projection.revision_id),
            "bundle_id": str(uow.transaction.projection.bundle_id),
            "fallback_reason": "provider unavailable", "error_code": "SAFE_FAILURE",
        } == read.json()["data"]
        cancel_url = f"/api/v1/runs/{run.run_id}/cancel"
        first_cancel = client.post(
            cancel_url, headers={"Idempotency-Key": "cancel-http-key"},
            json={"expected_version": 0},
        )
        replay_cancel = client.post(
            cancel_url, headers={"Idempotency-Key": "cancel-http-key"},
            json={"expected_version": 0},
        )
        assert first_cancel.status_code == replay_cancel.status_code == 200
        assert first_cancel.json()["data"] == replay_cancel.json()["data"]
        retry_url = f"/api/v1/runs/{run.run_id}/retry"
        first_retry = client.post(
            retry_url, headers={"Idempotency-Key": "retry-http-key"},
            json={"expected_version": 1},
        )
        replay_retry = client.post(
            retry_url, headers={"Idempotency-Key": "retry-http-key"},
            json={"expected_version": 1},
        )
        assert first_retry.status_code == replay_retry.status_code == 202
        assert first_retry.json()["data"]["run_id"] == replay_retry.json()["data"]["run_id"]
        assert first_retry.json()["data"]["run_id"] != str(run.run_id)


def test_get_run_exposes_ordered_candidates_and_select_is_idempotent() -> None:
    uow = FakeAIRunUOW()
    run = AIRun(
        run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
        thread_id="candidate-selection-http", status=AIRunStatus.MATERIALIZING, version=2,
    )
    candidate_a, candidate_b = uuid4(), uuid4()
    snapshot_a, snapshot_b = uuid4(), uuid4()
    preview_a, preview_b = uuid4(), uuid4()
    artifact_a, artifact_b = uuid4(), uuid4()
    uow.transaction.run = run
    uow.transaction.projection = AIRunProjection(
        run=run,
        candidates=(
            AIRunCandidateProjection(
                label="a", candidate_id=candidate_a, candidate_snapshot_id=snapshot_a,
                candidate_content_hash="a" * 64, preview_id=preview_a,
                preview_artifact_id=artifact_a, parent_candidate_snapshot_id=None,
                repair_status="not_requested",
            ),
            AIRunCandidateProjection(
                label="b", candidate_id=candidate_b, candidate_snapshot_id=snapshot_b,
                candidate_content_hash="b" * 64, preview_id=preview_b,
                preview_artifact_id=artifact_b, parent_candidate_snapshot_id=None,
                repair_status="not_requested",
            ),
        ),
        critique={
            "schema_version": "candidate-critique.v1",
            "recommended_candidate_id": str(candidate_b),
            "rationale": "B has stronger continuity.",
            "assessments": [
                {"candidate_id": str(candidate_a), "label": "a", "score": 70,
                 "evidence_refs": []},
                {"candidate_id": str(candidate_b), "label": "b", "score": 80,
                 "evidence_refs": []},
            ],
            "findings": [], "evidence": [], "repair_proposal": None,
        },
    )
    app = create_app(Settings.for_test(), ai_run_uow_factory=uow)  # type: ignore[arg-type]
    body = {
        "expected_version": 2, "preview_id": str(preview_b),
        "expected_candidate_id": str(candidate_b),
        "expected_candidate_content_hash": "b" * 64,
        "actor_id": "human-a", "selection_assertion": "I select candidate B now.",
        "decision": "select", "note": "reviewed",
    }
    url = f"/api/v1/runs/{run.run_id}/select-candidate"
    with TestClient(app) as client:
        read = client.get(f"/api/v1/runs/{run.run_id}")
        assert read.status_code == 200
        data = read.json()["data"]
        assert data["pending_action"] == "select_candidate"
        assert [item["label"] for item in data["candidates"]] == ["a", "b"]
        assert data["critique"]["recommended_candidate_id"] == str(candidate_b)
        first = client.post(url, headers={"Idempotency-Key": "select-http-key"}, json=body)
        replay = client.post(url, headers={"Idempotency-Key": "select-http-key"}, json=body)
        conflict = client.post(
            url, headers={"Idempotency-Key": "select-http-key"},
            json={**body, "preview_id": str(preview_a)},
        )
        assert first.status_code == replay.status_code == 200
        assert conflict.status_code == 409
