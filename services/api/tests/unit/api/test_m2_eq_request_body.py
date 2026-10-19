"""The new EQ HTTP contract is strict without changing legacy command coercion."""

import json
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from motif_forge.api import app as api_module
from motif_forge.api.app import CommandBatchBody, create_app
from motif_forge.application.revisions import CommitCommandBatchResult
from motif_forge.config import Settings
from motif_forge.domain.revisions import ChangeImpact
from pydantic import ValidationError


def _body():
    ids = [str(UUID(int=11)), str(UUID(int=12))]
    return {
        "branch_id": str(UUID(int=2)),
        "base_revision_id": str(UUID(int=3)),
        "client_sequence": 0,
        "reason": "HUMAN_STUDIO_EQ",
        "commands": [
            {
                "command_id": str(UUID(int=4)),
                "command_type": "set_piano_eq",
                "schema_version": "editor-command.v1",
                "actor_kind": "human",
                "client_sequence": 0,
                "selection": {"track_ids": ids},
                "payload": {
                    "eq": {
                        "schema_version": "piano-eq-state.v1",
                        "tracks": [
                            {
                                "track_id": identity,
                                "schema_version": "piano-eq.v1",
                                "profile_id": "motif-three-band-static.v1",
                                "bypass": False,
                                "low_gain_db": -8,
                                "mid_gain_db": 0,
                                "high_gain_db": 2,
                            }
                            for identity in ids
                        ],
                    }
                },
            }
        ],
    }


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("bypass", "false"),
        ("bypass", 0),
        ("low_gain_db", "-6.0"),
        ("mid_gain_db", True),
        ("high_gain_db", 12.01),
        ("profile_id", "unknown"),
    ],
)
def test_eq_body_rejects_coerced_values(parameter, value):
    body = _body()
    body["commands"][0]["payload"]["eq"]["tracks"][0][parameter] = value
    with pytest.raises(ValidationError):
        CommandBatchBody.model_validate_json(json.dumps(body))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameter,value", [("bypass", "false"), ("low_gain_db", "-6"), ("mid_gain_db", True)]
)
async def test_invalid_eq_http_is_422_before_any_transaction(parameter, value):
    writes = []

    def forbidden_uow():
        writes.append("transaction-started")
        raise AssertionError("invalid mix reached persistence")

    body = _body()
    body["commands"][0]["payload"]["eq"]["tracks"][0][parameter] = value
    app = create_app(Settings.for_test(), uow_factory=forbidden_uow)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{UUID(int=1)}/command-batches",
            json=body,
            headers={"Idempotency-Key": "invalid-mix-type-regression"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "REQUEST_VALIDATION_FAILED"
    assert writes == []


@pytest.mark.asyncio
async def test_legal_eq_json_uuids_numbers_and_booleans_reach_typed_commit(monkeypatch):
    received = []

    async def typed_commit(_self, request):
        received.append(request)
        eq = request.commands[0].payload.eq
        assert isinstance(eq.tracks[0].track_id, UUID)
        assert eq.tracks[0].low_gain_db == -8.0 and eq.tracks[0].mid_gain_db == 0.0
        assert eq.tracks[0].bypass is False and eq.tracks[0].high_gain_db == 2.0
        return CommitCommandBatchResult(
            project_id=request.project_id,
            branch_id=request.branch_id,
            revision_id=UUID(int=5),
            content_hash="a" * 64,
            actual_change_impact=ChangeImpact.L0,
        )

    monkeypatch.setattr(api_module.CommitCommandBatch, "__call__", typed_commit)
    app = create_app(Settings.for_test(), uow_factory=lambda: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/projects/{UUID(int=1)}/command-batches",
            json=_body(),
            headers={"Idempotency-Key": "valid-mix-type-regression"},
        )
    assert response.status_code == 201, response.text
    assert len(received) == 1
