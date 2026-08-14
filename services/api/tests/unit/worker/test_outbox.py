from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langgraph.types import Command
from motif_forge.agent.generate import PlanApprovalDecision
from motif_forge.agent.parent_graph import PARENT_TIME_STRETCH_RUN_TYPE
from motif_forge.domain.ai_runs import AIRun, AIRunStatus
from motif_forge.worker.outbox import (
    GraphActionPayload,
    OutboxMessage,
    ParentGraphActionPublisher,
    ParentGraphResumePublisher,
    dispatch_once,
)
from pydantic import ValidationError


class FakeStore:
    def __init__(self, messages: tuple[OutboxMessage, ...]) -> None:
        self.messages = messages
        self.published: list[UUID] = []
        self.failed: list[tuple[UUID, str]] = []

    async def claim_batch(self, **kwargs: object) -> tuple[OutboxMessage, ...]:
        del kwargs
        return self.messages

    async def mark_published(self, event_id: UUID, *, owner: str, published_at: datetime) -> bool:
        del owner, published_at
        self.published.append(event_id)
        return True

    async def mark_failed(
        self,
        event_id: UUID,
        *,
        owner: str,
        failed_at: datetime,
        error_code: str,
        attempts: int,
    ) -> bool:
        del owner, failed_at, attempts
        self.failed.append((event_id, error_code))
        return True


class FakePublisher:
    def __init__(self, *, fail_event_id: UUID | None = None) -> None:
        self.fail_event_id = fail_event_id
        self.published: list[UUID] = []

    async def publish(self, message: OutboxMessage) -> None:
        if message.event_id == self.fail_event_id:
            raise ConnectionError("broker unavailable")
        self.published.append(message.event_id)


class FakeResumableGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []
        self.values: dict[str, object] = {}

    async def aget_state(self, config: dict[str, object]) -> SimpleNamespace:
        del config
        return SimpleNamespace(values=self.values)

    async def ainvoke(self, input: object, config: dict[str, object]) -> object:
        self.calls.append((input, config))
        if isinstance(input, Command) and isinstance(input.resume, dict):
            event_id = input.resume.get("resume_event_id")
            if isinstance(event_id, str):
                self.values = {
                    "last_resume_event_id": event_id,
                    "terminal_status": "succeeded",
                }
        return {"terminal_status": "succeeded"}


def _message(*, attempts: int = 1) -> OutboxMessage:
    return OutboxMessage(
        event_id=uuid4(),
        topic="media.job.dispatch.requested",
        dedupe_key=f"dispatch:{uuid4()}",
        payload={"job_id": str(uuid4())},
        attempts=attempts,
    )


@pytest.mark.asyncio
async def test_dispatch_marks_only_successfully_published_messages() -> None:
    first = _message()
    second = _message()
    store = FakeStore((first, second))
    publisher = FakePublisher(fail_event_id=second.event_id)
    now = datetime.now(UTC)

    count = await dispatch_once(
        store,
        publisher,
        owner="dispatcher-test",
        batch_size=10,
        lease_seconds=30,
        clock=lambda: now,
    )

    assert count == 2
    assert publisher.published == [first.event_id]
    assert store.published == [first.event_id]
    assert store.failed == [(second.event_id, "OUTBOX_PUBLISH_FAILED")]


@pytest.mark.asyncio
async def test_parent_graph_publisher_resumes_the_payload_thread() -> None:
    graph = FakeResumableGraph()
    publisher = ParentGraphResumePublisher(graph)
    thread_id = f"parent-{uuid4().hex}"
    message = OutboxMessage(
        event_id=uuid4(),
        topic="graph.resume.requested",
        dedupe_key=f"resume:{uuid4()}",
        payload={
            "schema_version": "worker-resume.v1",
            "run_id": str(uuid4()),
            "thread_id": thread_id,
            "run_type": PARENT_TIME_STRETCH_RUN_TYPE,
            "resume_event_id": "worker-event-1",
            "job_id": str(uuid4()),
            "status": "succeeded",
            "artifact_id": str(uuid4()),
            "error_code": None,
        },
        attempts=1,
    )

    await publisher.publish(message)
    await publisher.publish(message)

    assert len(graph.calls) == 1
    command, config = graph.calls[0]
    assert isinstance(command, Command)
    assert config == {"configurable": {"thread_id": thread_id}}


@pytest.mark.asyncio
async def test_worker_resume_publisher_records_terminal_graph_progress() -> None:
    graph = FakeResumableGraph()
    recorded: list[dict[str, object]] = []

    async def record_progress(state: dict[str, object]) -> None:
        recorded.append(state)

    publisher = ParentGraphResumePublisher(graph, record_progress=record_progress)
    message = OutboxMessage(
        event_id=uuid4(),
        topic="graph.resume.requested",
        dedupe_key=f"resume:{uuid4()}",
        payload={
            "schema_version": "worker-resume.v1",
            "run_id": str(uuid4()),
            "thread_id": f"parent-{uuid4().hex}",
            "run_type": "parent.generate.v1",
            "resume_event_id": "worker-event-terminal",
            "job_id": str(uuid4()),
            "status": "succeeded",
            "artifact_id": str(uuid4()),
            "error_code": None,
        },
        attempts=1,
    )

    await publisher.publish(message)
    await publisher.publish(message)

    assert recorded == [
        {"terminal_status": "succeeded"},
        {
            "last_resume_event_id": "worker-event-terminal",
            "terminal_status": "succeeded",
        },
    ]


@pytest.mark.asyncio
async def test_parent_graph_publisher_rejects_non_parent_runs() -> None:
    graph = FakeResumableGraph()
    publisher = ParentGraphResumePublisher(graph)
    message = OutboxMessage(
        event_id=uuid4(),
        topic="graph.resume.requested",
        dedupe_key=f"resume:{uuid4()}",
        payload={
            "schema_version": "worker-resume.v1",
            "run_id": str(uuid4()),
            "thread_id": "direct-worker-test",
            "run_type": "time_stretch",
            "resume_event_id": "worker-event-direct",
            "job_id": str(uuid4()),
            "status": "failed_terminal",
            "artifact_id": None,
            "error_code": "FAILED",
        },
        attempts=1,
    )

    with pytest.raises(ValueError, match="does not target"):
        await publisher.publish(message)

    assert graph.calls == []


@pytest.mark.asyncio
async def test_complete_export_publisher_requires_exact_run_type() -> None:
    graph = FakeResumableGraph()
    publisher = ParentGraphResumePublisher(
        graph,
        run_type_prefix=None,
        run_type_exact="complete_song_export.v1",
    )
    message = OutboxMessage(
        event_id=uuid4(),
        topic="graph.resume.requested",
        dedupe_key=f"resume:{uuid4()}",
        payload={
            "schema_version": "worker-resume.v1",
            "run_id": str(uuid4()),
            "thread_id": "generate-export-exact",
            "run_type": "complete_song_export.v1.evil",
            "resume_event_id": "worker-event-wrong-type",
            "job_id": str(uuid4()),
            "status": "succeeded",
            "artifact_id": str(uuid4()),
            "error_code": None,
        },
        attempts=1,
    )

    with pytest.raises(ValueError, match="does not target"):
        await publisher.publish(message)

    assert graph.calls == []


def test_graph_action_payload_is_strict_and_targets_generate_only() -> None:
    payload = GraphActionPayload(
        action="resume",
        run_id=uuid4(),
        thread_id="generate-action-thread",
        run_type="parent.generate.v1",
        decision=PlanApprovalDecision(
            decision="approve",
            actor_id="test-user",
            approval_assertion="I authorize this exact persisted plan.",
            expected_plan_hash="a" * 64,
        ),
    )
    assert payload.schema_version == "graph-action.v1"

    with pytest.raises(ValidationError):
        GraphActionPayload.model_validate(
            {
                **payload.model_dump(mode="json"),
                "run_type": "parent.import.v1",
            }
        )
    with pytest.raises(ValidationError):
        GraphActionPayload.model_validate(
            {
                **payload.model_dump(mode="json"),
                "node_name": "MaterializeApprovedComposition",
            }
        )


@pytest.mark.asyncio
async def test_graph_action_publisher_rejects_topic_action_mismatch() -> None:
    class Loader:
        async def __call__(self, run_id: UUID) -> object:
            del run_id
            raise AssertionError("topic mismatch must fail before authoritative load")

    publisher = ParentGraphActionPublisher(FakeResumableGraph(), load_run=Loader())
    message = OutboxMessage(
        event_id=uuid4(),
        topic="graph.start.requested",
        dedupe_key=f"graph-action:{uuid4()}",
        payload={
            "schema_version": "graph-action.v1",
            "action": "cancel",
            "run_id": str(uuid4()),
            "thread_id": "generate-action-thread",
            "run_type": "parent.generate.v1",
            "decision": None,
        },
        attempts=1,
    )

    with pytest.raises(ValueError, match="topic"):
        await publisher.publish(message)


@pytest.mark.asyncio
async def test_graph_action_redelivery_continues_post_approval_checkpoint() -> None:
    graph = FakeResumableGraph()
    graph.values = {"phase": "approved"}
    run = AIRun(
        run_id=uuid4(),
        project_id=uuid4(),
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        thread_id="generate-approved-redelivery",
        status=AIRunStatus.MATERIALIZING,
        version=2,
    )

    class Loader:
        async def __call__(self, run_id: UUID) -> AIRun:
            assert run_id == run.run_id
            return run

    publisher = ParentGraphActionPublisher(graph, load_run=Loader())
    message = OutboxMessage(
        event_id=uuid4(),
        topic="graph.resume.requested",
        dedupe_key=f"resume:{uuid4()}",
        payload={
            "schema_version": "graph-action.v1",
            "action": "resume",
            "run_id": str(run.run_id),
            "thread_id": run.thread_id,
            "run_type": "parent.generate.v1",
            "decision": {
                "decision": "approve",
                "actor_id": "live-reviewer",
                "approval_assertion": "I approve this exact persisted composition plan.",
                "expected_plan_hash": "a" * 64,
                "note": "reviewed",
            },
        },
        attempts=2,
    )

    await publisher.publish(message)

    assert graph.calls == [
        (None, {"configurable": {"thread_id": run.thread_id}}),
    ]
