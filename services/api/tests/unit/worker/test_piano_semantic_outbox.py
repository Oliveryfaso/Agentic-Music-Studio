from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langgraph.types import Command
from motif_forge.domain.ai_runs import AIRun, AIRunStatus, AIRunType, EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.piano_requests import PianoSemanticRequest
from motif_forge.worker.outbox import OutboxMessage, ParentGraphActionPublisher


def _run(*, cancelled: bool = False) -> AIRun:
    semantic = PianoSemanticRequest(intent="增加低音钢琴伴奏", mode="append")
    return AIRun(
        run_id=UUID(int=1),
        project_id=UUID(int=2),
        branch_id=UUID(int=3),
        base_revision_id=UUID(int=4),
        thread_id="semantic-piano-parent",
        run_type=AIRunType.EDIT,
        edit_request=EditRunRequest(
            intent=semantic.intent, selection=Selection(), piano_request=semantic
        ).model_dump(mode="json"),
        status=AIRunStatus.CANCELLED if cancelled else AIRunStatus.QUEUED,
        terminal_at=datetime.now(UTC) if cancelled else None,
    )


def _message(run: AIRun, action: str = "start", decision: dict[str, object] | None = None):
    return OutboxMessage(
        event_id=uuid4(),
        topic=f"graph.{action}.requested",
        dedupe_key=f"{action}:{run.run_id}",
        attempts=1,
        payload={
            "schema_version": "graph-action.v1",
            "action": action,
            "run_id": str(run.run_id),
            "thread_id": run.thread_id,
            "run_type": "parent.edit.v1",
            "decision": decision,
        },
    )


class PianoParent:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = values or {}
        self.calls: list[object] = []

    async def aget_state(self, config: object, **kwargs: object):
        return SimpleNamespace(values=self.values, tasks=())

    def get_subgraphs(self):
        raise AssertionError("semantic piano must never inspect the legacy edit subgraph")

    async def ainvoke(self, value: object, config: object):
        self.calls.append(value)
        return {"phase": "waiting_piano_worker", "run_id": str(UUID(int=1))}


@pytest.mark.asyncio
async def test_semantic_start_uses_existing_piano_parent_initializer(monkeypatch) -> None:
    run, graph = _run(), PianoParent()

    async def load_run(run_id: UUID):
        assert run_id == run.run_id
        return run

    def initialize(**kwargs: object):
        request = kwargs["request"]
        assert request.project_id == run.project_id
        assert request.branch_id == run.branch_id
        assert request.base_revision_id == run.base_revision_id
        assert request.request_id == run.run_id
        assert request.semantic.intent == "增加低音钢琴伴奏"
        assert kwargs["run_id"] == run.run_id
        return {"phase": "received", "operation": "piano_preview", "run_id": str(run.run_id)}

    monkeypatch.setattr("motif_forge.worker.outbox.initial_piano_preview_state", initialize)
    await ParentGraphActionPublisher(graph, load_run=load_run).publish(_message(run))
    assert graph.calls == [
        {"phase": "received", "operation": "piano_preview", "run_id": str(run.run_id)}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["waiting_piano_worker", "waiting_piano_approval", "completed"])
async def test_repeated_start_at_piano_interrupt_does_not_restart_model(phase: str) -> None:
    run = _run()
    values = {"phase": phase}
    if phase == "completed":
        values["terminal_status"] = "succeeded"
    graph = PianoParent(values)

    async def load_run(run_id: UUID):
        return run

    await ParentGraphActionPublisher(graph, load_run=load_run).publish(_message(run))
    assert graph.calls == []


@pytest.mark.asyncio
async def test_semantic_generic_edit_resume_is_explicitly_refused() -> None:
    run = _run()
    graph = PianoParent({"phase": "waiting_piano_approval"})

    async def load_run(run_id: UUID):
        return run

    decision = {
        "action": "approve",
        "preview_id": str(UUID(int=8)),
        "expected_candidate_content_hash": "a" * 64,
        "actor_id": "human:local",
        "approval_assertion": "I approve this rendered piano candidate.",
    }
    with pytest.raises(ValueError, match="piano"):
        await ParentGraphActionPublisher(graph, load_run=load_run).publish(
            _message(run, "resume", decision)
        )
    assert graph.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["waiting_piano_worker", "waiting_piano_approval"])
async def test_semantic_cancel_resumes_parent_without_legacy_subgraph(phase: str) -> None:
    run, graph = _run(cancelled=True), PianoParent({"phase": phase})

    async def load_run(run_id: UUID):
        return run

    await ParentGraphActionPublisher(graph, load_run=load_run).publish(_message(run, "cancel"))
    assert len(graph.calls) == 1
    assert isinstance(graph.calls[0], Command)
    assert graph.calls[0].resume == {"action": "cancel"}


@pytest.mark.asyncio
async def test_terminal_semantic_ai_run_never_restarts_after_checkpoint_loss() -> None:
    run = _run().model_copy(
        update={"status": AIRunStatus.SUCCEEDED, "terminal_at": datetime.now(UTC)}
    )

    async def load_run(run_id: UUID):
        return run

    async def graph_for(loaded_run: AIRun):
        raise AssertionError("terminal semantic runs must not rebuild a paid graph")

    await ParentGraphActionPublisher(graph_for, load_run=load_run).publish(_message(run))
