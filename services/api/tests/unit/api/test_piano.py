from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from motif_forge.api.piano import build_piano_router
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_capability import PianoCapability


class Graph:
    def __init__(self):
        self.values = {}
        self.calls = []

    async def aget_state(self, config):
        return SimpleNamespace(values=self.values, next=(), tasks=())

    async def ainvoke(self, value, config):
        self.calls.append(value)
        if isinstance(value, dict):
            self.values = {**value, "phase": "waiting_piano_worker"}
        return self.values


@pytest.mark.asyncio
async def test_piano_api_replay_body_pin_scope_and_hash_guard():
    graph = Graph()

    async def capability():
        return PianoCapability(available=False, error_code="INSTRUMENT_PACK_UNAVAILABLE")

    app = FastAPI()
    app.include_router(build_piano_router(None, capability=capability, graph_getter=lambda: graph))

    @app.exception_handler(ApplicationError)
    async def error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"code": exc.code}, status_code=409)

    project, branch, base = uuid4(), uuid4(), uuid4()
    body = {
        "branch_id": str(branch),
        "base_revision_id": str(base),
        "performance_plan": {
            "notes": [
                {
                    "track_id": str(uuid4()),
                    "clip_id": str(uuid4()),
                    "note_id": str(uuid4()),
                    "velocity_override": 72,
                }
            ]
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        cap = await client.get("/api/v1/piano-capability")
        assert cap.json()["data"]["available"] is False
        url = f"/api/v1/projects/{project}/piano-previews"
        headers = {"Idempotency-Key": "piano-request-1"}
        first = await client.post(url, json=body, headers=headers)
        assert first.status_code == 202
        thread = first.json()["data"]["thread_id"]
        again = await client.post(url, json=body, headers=headers)
        assert again.json()["data"]["replayed"] and len(graph.calls) == 1
        changed = await client.post(url, json={**body, "seed": 1}, headers=headers)
        assert changed.status_code == 409 and len(graph.calls) == 1
        alien = await client.get(f"/api/v1/projects/{uuid4()}/piano-previews/{thread}")
        assert alien.status_code == 409
        graph.values.update(
            phase="waiting_piano_approval", piano_data={"candidate_content_hash": "b" * 64}
        )
        decision = await client.post(
            url + "/" + thread + "/decision",
            json={
                "action": "approve",
                "expected_candidate_content_hash": "c" * 64,
                "approval_assertion": "Approve this exact piano candidate.",
            },
        )
        assert decision.json()["code"] == "PIANO_CANDIDATE_HASH_MISMATCH" and len(graph.calls) == 1
