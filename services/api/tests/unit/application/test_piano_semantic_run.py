from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from motif_forge.application.ai_runs import graph_progress_target
from motif_forge.application.edit_runs import CreateEditAIRun, CreateEditAIRunRequest
from motif_forge.domain.ai_runs import AIRunStatus, EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.piano_requests import PianoSemanticRequest


@pytest.mark.asyncio
async def test_create_semantic_run_persists_new_state_and_one_call_budget() -> None:
    semantic = PianoSemanticRequest(intent="低音区稀疏钢琴伴奏", mode="append")
    tx = SimpleNamespace(
        get_ai_run_idempotency=AsyncMock(return_value=None), create_ai_run=AsyncMock()
    )

    class Uow:
        async def __aenter__(self):
            return tx

        async def __aexit__(self, *args: object):
            return None

    run = await CreateEditAIRun(Uow)(
        CreateEditAIRunRequest(
            project_id=UUID(int=2),
            branch_id=UUID(int=3),
            base_revision_id=UUID(int=4),
            thread_id="semantic-create",
            idempotency_key="semantic-request-1",
            edit_request=EditRunRequest(
                intent=semantic.intent, selection=Selection(), piano_request=semantic
            ),
            max_model_requests=1,
            max_total_tokens=12000,
        )
    )
    stored = tx.create_ai_run.await_args.kwargs["run"]
    assert stored == run
    assert stored.state_schema_version == "piano-accompaniment-run.v1"
    assert stored.max_model_requests == 1
    assert stored.max_total_tokens == 12000


def test_piano_worker_and_terminal_progress_reference_same_ai_run() -> None:
    run_id, revision_id = UUID(int=1), UUID(int=2)
    assert graph_progress_target({"run_id": str(run_id), "phase": "waiting_piano_worker"}) == (
        run_id,
        AIRunStatus.WAITING_WORKER,
        None,
        None,
    )
    assert graph_progress_target(
        {
            "run_id": str(run_id),
            "terminal_status": "succeeded",
            "piano_revision_id": str(revision_id),
        }
    ) == (run_id, AIRunStatus.SUCCEEDED, None, revision_id)
    # Artifact attachment owns pending-preview identity, not this loose phase mapper.
    assert graph_progress_target({"run_id": str(run_id), "phase": "waiting_piano_approval"}) is None


@pytest.mark.asyncio
async def test_legacy_edit_idempotency_fingerprint_does_not_gain_new_null_field() -> None:
    from motif_forge.application._hashing import request_hash
    from motif_forge.application.edit_runs import CREATE_EDIT_RUN_OPERATION

    request = CreateEditAIRunRequest(
        project_id=UUID(int=2),
        branch_id=UUID(int=3),
        base_revision_id=UUID(int=4),
        thread_id="legacy-edit-replay",
        idempotency_key="legacy-edit-request",
        edit_request=EditRunRequest(intent="降低2dB", selection=Selection()),
    )
    old_payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    del old_payload["edit_request"]["piano_request"]
    expected = request_hash({"schema": CREATE_EDIT_RUN_OPERATION, **old_payload})
    tx = SimpleNamespace(
        get_ai_run_idempotency=AsyncMock(return_value=None), create_ai_run=AsyncMock()
    )

    class Uow:
        async def __aenter__(self):
            return tx

        async def __aexit__(self, *args: object):
            return None

    await CreateEditAIRun(Uow)(request)
    assert tx.create_ai_run.await_args.kwargs["request_hash"] == expected
