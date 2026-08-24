"""Real PostgreSQL boundary for one high-impact Edit Run approval loop."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from motif_forge.application.edit_decisions import (
    ApplyEditPreviewDecision,
    AttachEditPreviewArtifact,
    CreateEditPreview,
    EditPreviewDecision,
    RecordEditPreviewDecision,
)
from motif_forge.application.edit_runs import CreateEditAIRun, CreateEditAIRunRequest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.domain.ai_runs import AIRunStatus, EditRunRequest
from motif_forge.domain.commands import (
    AddTrackCommand,
    AddTrackPayload,
    Selection,
    SetTrackParamCommand,
    SetTrackParamPayload,
)
from motif_forge.domain.editing import EditPatchProposal, EditVersionRefs
from motif_forge.domain.ir import Track, TrackRole, TrackType
from motif_forge.domain.revisions import AuthorKind, ChangeImpact
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from sqlalchemy import func, select

from .test_postgres_ai_runs import _upgrade
from .test_postgres_generate_materialization import _delete_exact_project


@pytest.mark.asyncio
async def test_edit_preview_decision_restarts_and_materializes_once(
    test_postgres_dsn: str,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai_runs = PostgresAIRunUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name="S6 Edit approval",
            actor_id="integration-human",
            idempotency_key=f"s6-project-{uuid4().hex}",
        )
    )
    run_id = UUID(int=0)
    try:
        track_id = uuid4()
        seeded = await CommitCommandBatch(projects)(
            CommitCommandBatchRequest(
                project_id=project.project_id,
                branch_id=project.active_branch_id,
                base_revision_id=project.root_revision_id,
                commands=(
                    AddTrackCommand(
                        command_id=uuid4(),
                        actor_kind="human",
                        client_sequence=0,
                        payload=AddTrackPayload(
                            track=Track(
                                track_id=track_id,
                                track_type=TrackType.INSTRUMENT,
                                name="Pad",
                                role=TrackRole.HARMONY,
                            )
                        ),
                    ),
                ),
                actor_id="integration-human",
                author_kind=AuthorKind.HUMAN,
                reason="S6_TEST_SEED",
                idempotency_key=f"s6-seed-{uuid4().hex}",
            )
        )
        create_request = CreateEditAIRunRequest(
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=seeded.revision_id,
            thread_id=f"s6-edit-{uuid4().hex}",
            edit_request=EditRunRequest(
                intent="change the selected Pad timbre",
                selection=Selection(track_ids=(track_id,), start_tick=0, end_tick=1920),
            ),
            idempotency_key=f"s6-edit-run-{uuid4().hex}",
        )
        created = await CreateEditAIRun(ai_runs)(create_request)
        replayed = await CreateEditAIRun(ai_runs)(create_request)
        run_id = created.run_id
        assert replayed.run_id == created.run_id

        proposal = EditPatchProposal(
            proposal_id=uuid4(),
            project_id=project.project_id,
            branch_id=project.active_branch_id,
            base_revision_id=seeded.revision_id,
            selection=create_request.edit_request.selection,
            commands=(
                SetTrackParamCommand(
                    command_id=uuid4(),
                    actor_kind="agent",
                    client_sequence=0,
                    selection=create_request.edit_request.selection,
                    payload=SetTrackParamPayload(
                        track_id=track_id,
                        parameter="instrument_ref",
                        value="synth.pad.glass",
                    ),
                ),
            ),
            rationale="bounded timbre edit",
            expected_effect="replace the selected Pad timbre",
            predicted_change_impact=ChangeImpact.L2,
            confidence=1,
            versions=EditVersionRefs(prompt="s6-test", model="deterministic"),
        )
        preview = await CreateEditPreview(projects, run_id=created.run_id)(proposal, {}, {})
        preview_id = UUID(str(preview["pending_preview_id"]))
        artifact_id = uuid4()
        await AttachEditPreviewArtifact(
            projects, run_id=created.run_id, ai_uow_factory=ai_runs
        )(
            preview_id=preview_id,
            candidate_snapshot_id=UUID(str(preview["candidate_snapshot_id"])),
            expected_candidate_content_hash=str(preview["candidate_content_hash"]),
            preview_artifact_id=artifact_id,
        )
        decision = EditPreviewDecision(
            action="approve",
            preview_id=preview_id,
            expected_candidate_content_hash=str(preview["candidate_content_hash"]),
            actor_id="integration-human",
            approval_assertion="I approve this rendered S6 edit.",
        )
        recorder = RecordEditPreviewDecision(ai_runs, project_uow_factory=projects)
        await recorder(
            run_id=created.run_id,
            decision=decision,
            idempotency_key="s6-edit-decision-fixed",
        )
        await recorder(
            run_id=created.run_id,
            decision=decision,
            idempotency_key="s6-edit-decision-fixed",
        )
        changed = decision.model_copy(update={"note": "different"})
        with pytest.raises(ApplicationError) as captured:
            await recorder(
                run_id=created.run_id,
                decision=changed,
                idempotency_key="s6-edit-decision-fixed",
            )
        assert captured.value.code == "EDIT_DECISION_CONFLICT"

        materializer = ApplyEditPreviewDecision(projects, run_id=created.run_id)
        first = await materializer(decision)
        second = await materializer(decision)
        assert first["materialized_revision_id"] == second["materialized_revision_id"]
        async with sessions() as session:
            from motif_forge.infrastructure.persistence.tables import (
                AIRunEditDecisionRow,
                AIRunRow,
                RevisionRow,
            )

            status = await session.scalar(select(AIRunRow.status).where(AIRunRow.id == run_id))
            decision_count = await session.scalar(
                select(func.count()).select_from(AIRunEditDecisionRow).where(
                    AIRunEditDecisionRow.run_id == run_id
                )
            )
            revision_count = await session.scalar(
                select(func.count()).select_from(RevisionRow).where(
                    RevisionRow.project_id == project.project_id
                )
            )
        assert status == AIRunStatus.WAITING_EDIT_APPROVAL.value
        assert decision_count == 1
        assert revision_count == 3  # root, human seed, approved edit
    finally:
        await _delete_exact_project(engine, project.project_id, run_id)
        await engine.dispose()
