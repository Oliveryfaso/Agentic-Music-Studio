from __future__ import annotations

from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from motif_forge.agent.parent_graph import build_parent_graph, initial_export_state
from motif_forge.application.revision_exports import RevisionExportRequest
from motif_forge.domain.export_plan import CompleteExportCursorV2, ExportPlanV2


@pytest.mark.asyncio
async def test_export_resumes_on_rebuilt_parent_and_cancels_without_an_ai_run() -> None:
    project, revision, request_id, track = (uuid4() for _ in range(4))
    request = RevisionExportRequest(
        project_id=project, revision_id=revision, request_id=request_id, include_mp3=False
    )
    plan = ExportPlanV2(
        project_id=project,
        revision_id=revision,
        request_id=request_id,
        arrangement_hash="a" * 64,
        seed=0,
        track_ids=(track,),
        include_mp3=False,
    )
    job, run = uuid4(), uuid4()
    calls = []

    async def prepare(request, *, thread_id):
        return CompleteExportCursorV2(
            plan=plan, plan_hash=plan.content_hash, thread_id=thread_id, run_type="parent.export.v1"
        )

    async def enqueue(cursor):
        calls.append("enqueue")
        return cursor.model_copy(
            update={
                "media_run_id": run,
                "pending_job_id": job,
                "pending_idempotency_key": "test-export-key",
            }
        )

    async def collect(cursor, *, completed_job_id):
        raise AssertionError("cancel must not collect or enqueue more work")

    async def cancel(**kwargs):
        calls.append(("cancel", kwargs))

    async def unused(request):
        raise AssertionError("export must use the existing export application services")

    saver = InMemorySaver()

    def graph():
        return build_parent_graph(
            unused,
            checkpointer=saver,
            prepare_revision_export=prepare,
            cancel_revision_export=cancel,
            enqueue_next_complete_export_job=enqueue,
            collect_complete_export_artifact=collect,
        )

    config = {"configurable": {"thread_id": "finite-export"}}
    first = await graph().ainvoke(
        initial_export_state(thread_id="finite-export", request=request), config
    )
    assert first["phase"] == "waiting_export_worker"
    assert first["plan_hash"] == plan.content_hash
    resumed = await graph().ainvoke(Command(resume={"action": "cancel"}), config)
    assert resumed["terminal_status"] == "cancelled"
    assert calls[0] == "enqueue" and len(calls) == 2
    assert calls[1][1] == {"project_id": project, "run_id": run, "thread_id": "finite-export"}


def test_export_request_rejects_ambiguous_stems() -> None:
    with pytest.raises(ValueError, match="EXPORT_STEM_SELECTION_AMBIGUOUS"):
        RevisionExportRequest(
            project_id=uuid4(),
            revision_id=uuid4(),
            request_id=uuid4(),
            include_all_stems=True,
            stem_track_ids=(uuid4(),),
        )


@pytest.mark.asyncio
async def test_duplicate_worker_event_resumes_post_collect_node_after_interruption() -> None:
    from motif_forge.domain.export_plan import export_key_v2
    from motif_forge.worker.outbox import OutboxMessage, ParentGraphResumePublisher

    project, revision, track, run, master, bundle, audio = (uuid4() for _ in range(7))
    plan = ExportPlanV2(
        project_id=project,
        revision_id=revision,
        arrangement_hash="a" * 64,
        seed=0,
        track_ids=(track,),
        include_mp3=False,
    )
    calls = 0
    collects = 0

    async def prepare(request, *, thread_id):
        return CompleteExportCursorV2(
            plan=plan, plan_hash=plan.content_hash, thread_id=thread_id, run_type="parent.export.v1"
        )

    async def enqueue(cursor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated interruption after Collect checkpoint")
        return cursor.model_copy(
            update={
                "media_run_id": run,
                "pending_job_id": master if not cursor.completed_steps else bundle,
                "pending_idempotency_key": export_key_v2(plan, cursor.pending_steps[0]),
            }
        )

    async def collect(cursor, *, completed_job_id):
        nonlocal collects
        collects += 1
        return cursor.model_copy(
            update={
                "completed_steps": ("master",),
                "completed_job_ids": (master,),
                "audio_artifact_ids": (audio,),
                "pending_job_id": None,
                "pending_idempotency_key": None,
            }
        )

    async def unused(*args, **kwargs):
        raise AssertionError("unexpected service")

    graph = build_parent_graph(
        unused,
        checkpointer=InMemorySaver(),
        prepare_revision_export=prepare,
        cancel_revision_export=unused,
        enqueue_next_complete_export_job=enqueue,
        collect_complete_export_artifact=collect,
    )
    thread = "export-duplicate-event"
    config = {"configurable": {"thread_id": thread}}
    await graph.ainvoke(
        initial_export_state(
            thread_id=thread,
            request=RevisionExportRequest(
                project_id=project, revision_id=revision, request_id=uuid4(), include_mp3=False
            ),
        ),
        config,
    )
    message = OutboxMessage(
        event_id=uuid4(),
        topic="graph.resume.requested",
        dedupe_key="recovery-event",
        attempts=0,
        payload={
            "schema_version": "worker-resume.v1",
            "run_id": str(run),
            "thread_id": thread,
            "run_type": "parent.export.v1",
            "job_id": str(master),
            "status": "succeeded",
            "artifact_id": str(audio),
            "resume_event_id": "master-completed",
        },
    )
    publisher = ParentGraphResumePublisher(graph)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        await publisher.publish(message)
    assert (await graph.aget_state(config)).values["last_resume_event_id"] == "master-completed"
    await publisher.publish(message)
    values = (await graph.aget_state(config)).values
    assert values["phase"] == "waiting_export_worker" and values["pending_job_id"] == str(bundle)
    await publisher.publish(message)
    assert calls == 3 and collects == 1
