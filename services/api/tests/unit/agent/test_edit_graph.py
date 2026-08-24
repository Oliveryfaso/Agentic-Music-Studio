from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from motif_forge.agent.edit import (
    BoundedEditContext,
    EditGraphDependencies,
    build_edit_subgraph,
    initial_edit_state,
)
from motif_forge.application.candidate_previews import CandidatePreviewCursor
from motif_forge.application.edit_decisions import EditPreviewDecision
from motif_forge.domain.ai_runs import EditRunRequest
from motif_forge.domain.commands import Selection, SetTrackParamCommand, SetTrackParamPayload
from motif_forge.domain.editing import EditPatchProposal, EditVersionRefs
from motif_forge.domain.ir import ArrangementIR, Section, Track, TrackRole, TrackType
from motif_forge.domain.revisions import ChangeImpact


def uid(value: int) -> UUID:
    return UUID(int=value)


@pytest.mark.asyncio
async def test_fallback_edit_graph_routes_explicit_gain_to_auto_commit() -> None:
    base = ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=3840, label="A"),),
        tracks=(
            Track(
                track_id=uid(3), track_type=TrackType.INSTRUMENT, name="Pad", role=TrackRole.HARMONY
            ),
        ),
    )
    request = EditRunRequest(
        intent="把这里的 Pad 降低 2 dB",
        selection=Selection(track_ids=(uid(3),), start_tick=0, end_tick=1920),
    )

    graph = build_edit_subgraph(
        EditGraphDependencies(
            load_context=lambda _request: BoundedEditContext.from_arrangement(base, _request),
            planner=None,
        ),
        checkpointer=MemorySaver(),
    )
    result = await graph.ainvoke(
        initial_edit_state(
            thread_id="edit-test",
            project_id=uid(1),
            branch_id=uid(4),
            base_revision_id=uid(5),
            request=request,
            base_arrangement=base,
        ),
        {"configurable": {"thread_id": "edit-test"}},
    )

    assert result["edit_route"] == "auto_commit"
    assert result["simulation"]["actual_change_impact"] == 0
    assert result["planner_context"]["contains_full_arrangement"] is False


@pytest.mark.asyncio
async def test_fallback_rejects_unsupported_intent_without_model() -> None:
    base = ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=3840, label="A"),),
        tracks=(
            Track(
                track_id=uid(3), track_type=TrackType.INSTRUMENT, name="Pad", role=TrackRole.HARMONY
            ),
        ),
    )
    request = EditRunRequest(
        intent="重新创作整首歌",
        selection=Selection(track_ids=(uid(3),), start_tick=0, end_tick=1920),
    )
    graph = build_edit_subgraph(
        EditGraphDependencies(
            load_context=lambda _request: BoundedEditContext.from_arrangement(base, _request),
            planner=None,
        )
    )
    result = await graph.ainvoke(
        initial_edit_state(
            thread_id="edit-fail",
            project_id=uid(1),
            branch_id=uid(4),
            base_revision_id=uid(5),
            request=request,
            base_arrangement=base,
        )
    )
    assert result["phase"] == "failed"
    assert result["error_code"] == "EDIT_FALLBACK_UNSUPPORTED"


@pytest.mark.asyncio
async def test_high_impact_edit_waits_for_rendered_artifact_before_approval() -> None:
    base = ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=3840, label="A"),),
        tracks=(
            Track(
                track_id=uid(3), track_type=TrackType.INSTRUMENT, name="Pad", role=TrackRole.HARMONY
            ),
        ),
    )
    request = EditRunRequest(
        intent="add a melody counterline",
        selection=Selection(track_ids=(uid(3),), start_tick=0, end_tick=1920),
    )
    proposal_id = uuid4()
    candidate_id = uuid4()
    preview_id = uuid4()
    media_run_id = uuid4()
    job_id = uuid4()
    artifact_id = uuid4()
    attached: list[UUID] = []

    async def planner(context: BoundedEditContext) -> EditPatchProposal:
        return EditPatchProposal(
            proposal_id=proposal_id,
            project_id=context.project_id,
            branch_id=context.branch_id or uid(4),
            base_revision_id=context.base_revision_id or uid(5),
            selection=context.selection,
            commands=(
                SetTrackParamCommand(
                    command_id=uuid4(), actor_kind="agent", client_sequence=0,
                    selection=context.selection,
                    payload=SetTrackParamPayload(
                        track_id=uid(3), parameter="instrument_ref", value="synth.lead.soft"
                    ),
                ),
            ),
            rationale="bounded melody addition",
            expected_effect="new local counterline",
            predicted_change_impact=ChangeImpact.L2,
            confidence=1,
            versions=EditVersionRefs(prompt="test", model="fake"),
        )

    async def create_preview(*_args: object) -> dict[str, object]:
        return {
            "pending_preview_id": str(preview_id),
            "candidate_snapshot_id": str(candidate_id),
            "candidate_content_hash": "a" * 64,
        }

    async def enqueue(_request: object) -> CandidatePreviewCursor:
        return CandidatePreviewCursor(
            project_id=uid(1), candidate_snapshot_id=candidate_id,
            candidate_content_hash="a" * 64, media_run_id=media_run_id, job_id=job_id,
        )

    async def collect(
        cursor: CandidatePreviewCursor, completed_job_id: UUID
    ) -> CandidatePreviewCursor:
        assert completed_job_id == job_id
        return cursor.model_copy(update={"preview_artifact_id": artifact_id})

    async def attach(
        cursor: CandidatePreviewCursor, _state: dict[str, object]
    ) -> dict[str, object]:
        assert cursor.preview_artifact_id is not None
        attached.append(cursor.preview_artifact_id)
        return {"preview_artifact_id": str(cursor.preview_artifact_id)}

    async def decide(_decision: EditPreviewDecision) -> dict[str, object]:
        return {}

    graph = build_edit_subgraph(
        EditGraphDependencies(
            load_context=lambda value: BoundedEditContext.from_arrangement(base, value),
            planner=planner,
            create_preview=create_preview,
            enqueue_candidate_preview=enqueue,
            collect_candidate_preview=collect,
            attach_preview_artifact=attach,
            apply_decision=decide,
        ),
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "edit-render"}}
    first = await graph.ainvoke(
        initial_edit_state(
            thread_id="edit-render", run_id=uid(8), project_id=uid(1),
            branch_id=uid(4), base_revision_id=uid(5), request=request,
            base_arrangement=base,
        ),
        config,
    )
    assert first["phase"] == "waiting_worker", first
    assert attached == []

    second = await graph.ainvoke(
        Command(resume={
            "schema_version": "worker-resume.v1", "run_id": str(media_run_id),
            "thread_id": "edit-render", "run_type": "parent.candidate_preview.v1",
            "resume_event_id": "event-1", "job_id": str(job_id),
            "status": "succeeded", "artifact_id": str(artifact_id),
        }),
        config,
    )
    assert second["phase"] == "waiting_edit_approval"
    assert attached == [artifact_id]
    assert second["preview_artifact_id"] == str(artifact_id)
