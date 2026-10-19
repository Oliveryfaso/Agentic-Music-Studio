from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from motif_forge.api.ai_runs import build_ai_run_router
from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import AIRunProjection
from motif_forge.domain.ai_runs import AIRun, AIRunType, EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.piano_requests import PianoSemanticRequest


@pytest.mark.parametrize(
    "operation,body",
    [
        ("cancel", {"expected_version": 0}),
        ("retry", {"expected_version": 0}),
        (
            "replan",
            {"expected_version": 0, "expected_plan_hash": "a" * 64, "adjustment": {"note": "更轻"}},
        ),
        (
            "resume",
            {
                "expected_version": 0,
                "expected_plan_hash": "a" * 64,
                "actor_id": "human:local",
                "approval_assertion": "I approve this rendered candidate.",
            },
        ),
        (
            "select-candidate",
            {
                "expected_version": 0,
                "decision": "reject",
                "actor_id": "human:local",
                "selection_assertion": "I reject these rendered candidates.",
            },
        ),
        (
            "edit-decision",
            {
                "action": "approve",
                "preview_id": str(UUID(int=5)),
                "expected_candidate_content_hash": "a" * 64,
                "actor_id": "human:local",
                "approval_assertion": "I approve this rendered candidate.",
            },
        ),
    ],
)
def test_generic_run_actions_refuse_piano_semantics_before_mutation(operation, body) -> None:
    client, _ = _client()
    response = client.post(
        f"/api/v1/runs/{UUID(int=1)}/{operation}",
        json=body,
        headers={"Idempotency-Key": "blocked-semantic-action"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PIANO_SEMANTIC_ENDPOINT_REQUIRED"


def _client():
    semantic = PianoSemanticRequest(intent="低音伴奏", mode="append")
    run = AIRun(
        run_id=UUID(int=1),
        project_id=UUID(int=2),
        branch_id=UUID(int=3),
        base_revision_id=UUID(int=4),
        thread_id="piano-api-guard",
        run_type=AIRunType.EDIT,
        edit_request=EditRunRequest(
            intent=semantic.intent, selection=Selection(), piano_request=semantic
        ).model_dump(mode="json"),
    )

    class ReadOnlyUow:
        def __call__(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object):
            return None

        async def read_ai_run(self, run_id: UUID):
            assert run_id == run.run_id
            return run

        async def read_ai_run_projection(self, run_id: UUID):
            return AIRunProjection(run=await self.read_ai_run(run_id))

        # No mutation methods: any attempted write fails this test immediately.

    app = FastAPI()

    @app.exception_handler(ApplicationError)
    async def error_handler(request, error: ApplicationError):
        return JSONResponse(status_code=400, content={"code": error.code})

    app.include_router(build_ai_run_router(ReadOnlyUow()))
    return TestClient(app), run


def test_semantic_run_stays_readable_from_generic_read_endpoint() -> None:
    client, run = _client()
    response = client.get(f"/api/v1/runs/{run.run_id}")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["edit_request"]["piano_request"]["mode"] == "append"


def test_generic_create_cannot_bypass_piano_request_budget_policy() -> None:
    client, run = _client()
    response = client.post(
        f"/api/v1/projects/{run.project_id}/ai-runs",
        json={
            "run_type": "edit",
            "branch_id": str(run.branch_id),
            "base_revision_id": str(run.base_revision_id),
            "edit_request": run.edit_request,
            "max_model_requests": 3,
            "max_total_tokens": 12000,
        },
        headers={"Idempotency-Key": "blocked-semantic-create"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "PIANO_SEMANTIC_ENDPOINT_REQUIRED"
