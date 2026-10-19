from __future__ import annotations

from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from motif_forge.agent.parent_graph import build_parent_graph, initial_piano_preview_state
from motif_forge.agent.piano_preview import PianoPreviewNodes
from motif_forge.application.candidate_previews import CandidatePreviewCursor
from motif_forge.application.piano_preview import (
    PianoPrepared,
    PianoPreviewRequest,
)
from motif_forge.application.previews import DecidePreviewResult
from motif_forge.domain.revisions import PreviewStatus


class FakePianoServices:
    def __init__(self):
        (
            self.project,
            self.branch,
            self.base,
            self.request,
            self.preview,
            self.baseline,
            self.candidate,
        ) = [uuid4() for _ in range(7)]
        self.jobs = {name: (uuid4(), uuid4(), uuid4()) for name in ("baseline", "piano")}
        self.enqueued = []
        self.decisions = []
        self.cancelled = []

    async def prepare(self, request, *, thread_id):
        return PianoPrepared(
            project_id=self.project,
            branch_id=self.branch,
            base_revision_id=self.base,
            request_id=self.request,
            thread_id=thread_id,
            preview_id=self.preview,
            baseline_snapshot_id=self.baseline,
            baseline_content_hash="a" * 64,
            candidate_snapshot_id=self.candidate,
            candidate_content_hash="b" * 64,
            seed=0,
        )

    async def enqueue(self, prepared, *, step):
        self.enqueued.append(step)
        run, job, _ = self.jobs[step]
        return CandidatePreviewCursor(
            project_id=self.project,
            candidate_snapshot_id=self.baseline if step == "baseline" else self.candidate,
            candidate_content_hash="a" * 64 if step == "baseline" else "b" * 64,
            media_run_id=run,
            job_id=job,
        )

    async def collect(self, prepared, cursor, *, step):
        return cursor.model_copy(update={"preview_artifact_id": self.jobs[step][2]})

    async def decide(self, prepared, decision, cursor):
        self.decisions.append(decision)
        return DecidePreviewResult(
            preview_id=self.preview, status=PreviewStatus.APPROVED, revision_id=uuid4()
        )

    async def cancel(self, prepared, cursor):
        self.cancelled.append(cursor.job_id)


def worker(service, step, thread):
    run, job, artifact = service.jobs[step]
    return {
        "schema_version": "worker-resume.v1",
        "run_id": str(run),
        "job_id": str(job),
        "thread_id": thread,
        "run_type": "parent.piano_preview.v1",
        "resume_event_id": step + "-done",
        "status": "succeeded",
        "artifact_id": str(artifact),
    }


@pytest.mark.asyncio
async def test_same_parent_piano_waits_for_both_auditions_and_exact_human_approval():
    service = FakePianoServices()
    saver = InMemorySaver()

    async def unused(*args, **kwargs):
        raise AssertionError("no unrelated or model calls")

    def graph():
        return build_parent_graph(
            unused, checkpointer=saver, piano_preview_nodes=PianoPreviewNodes(service)
        )

    thread = "piano-unit"
    config = {"configurable": {"thread_id": thread}}
    request = PianoPreviewRequest(
        project_id=service.project,
        branch_id=service.branch,
        base_revision_id=service.base,
        request_id=service.request,
    )
    state = await graph().ainvoke(
        initial_piano_preview_state(thread_id=thread, request=request), config
    )
    assert state["phase"] == "waiting_piano_worker" and service.enqueued == ["baseline"]
    state = await graph().ainvoke(Command(resume=worker(service, "baseline", thread)), config)
    assert service.enqueued == ["baseline", "piano"] and not service.decisions
    state = await graph().ainvoke(Command(resume=worker(service, "piano", thread)), config)
    assert state["phase"] == "waiting_piano_approval" and not service.decisions
    assert state["piano_artifact_id"] == str(service.jobs["piano"][2])
    bad = await graph().ainvoke(
        Command(
            resume={
                "action": "approve",
                "expected_candidate_content_hash": "c" * 64,
                "approval_assertion": "I approve this exact piano candidate.",
            }
        ),
        config,
    )
    assert bad["phase"] == "waiting_piano_approval" and not service.decisions
    done = await graph().ainvoke(
        Command(
            resume={
                "action": "approve",
                "expected_candidate_content_hash": "b" * 64,
                "approval_assertion": "I approve this exact piano candidate.",
            }
        ),
        config,
    )
    assert (
        done["phase"] == "completed" and done["piano_revision_id"] and len(service.decisions) == 1
    )


@pytest.mark.asyncio
async def test_piano_cancel_does_not_commit_the_candidate():
    service = FakePianoServices()

    async def unused(*args, **kwargs):
        raise AssertionError("unexpected")

    graph = build_parent_graph(
        unused, checkpointer=InMemorySaver(), piano_preview_nodes=PianoPreviewNodes(service)
    )
    config = {"configurable": {"thread_id": "piano-cancel"}}
    await graph.ainvoke(
        initial_piano_preview_state(
            thread_id="piano-cancel",
            request=PianoPreviewRequest(
                project_id=service.project,
                branch_id=service.branch,
                base_revision_id=service.base,
                request_id=service.request,
            ),
        ),
        config,
    )
    done = await graph.ainvoke(Command(resume={"action": "cancel"}), config)
    assert done["terminal_status"] == "cancelled" and service.cancelled and not service.decisions
