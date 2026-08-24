from uuid import UUID

from motif_forge.domain.ai_runs import AIRun, AIRunType, EditRunRequest
from motif_forge.domain.commands import Selection


def test_edit_run_identity_forbids_generate_brief() -> None:
    run = AIRun(
        run_id=UUID(int=1),
        project_id=UUID(int=2),
        branch_id=UUID(int=3),
        base_revision_id=UUID(int=4),
        thread_id="edit-1",
        run_type=AIRunType.EDIT,
        edit_request=EditRunRequest(
            intent="降低 2 dB",
            selection=Selection(track_ids=(UUID(int=5),), start_tick=0, end_tick=960),
        ).model_dump(mode="json"),
        max_model_requests=1,
        max_total_tokens=2000,
    )
    assert run.run_type is AIRunType.EDIT
    assert run.brief is None
    assert run.state_schema_version == "edit-run-state.v1"
