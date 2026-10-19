from uuid import UUID

import pytest
from motif_forge.domain.ai_runs import AIRun, AIRunType, EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.piano_requests import PianoSemanticRequest
from pydantic import ValidationError


def _run(request: EditRunRequest, **overrides: object) -> AIRun:
    return AIRun(
        run_id=UUID(int=1),
        project_id=UUID(int=2),
        branch_id=UUID(int=3),
        base_revision_id=UUID(int=4),
        thread_id="piano-semantic",
        run_type=AIRunType.EDIT,
        edit_request=request.model_dump(mode="json"),
        **overrides,
    )


def test_semantic_append_uses_explicit_state_version_and_legacy_stays_unchanged() -> None:
    semantic = PianoSemanticRequest(intent="前八小节稀疏, 后八小节活跃", mode="append")
    request = EditRunRequest(intent=semantic.intent, selection=Selection(), piano_request=semantic)
    run = _run(request)
    assert run.state_schema_version == "piano-accompaniment-run.v1"
    assert run.run_type is AIRunType.EDIT
    assert EditRunRequest.model_validate_json(request.model_dump_json(), strict=True) == request
    assert _run(EditRunRequest(intent="降低2dB", selection=Selection())).state_schema_version == (
        "edit-run-state.v1"
    )
    with pytest.raises(ValidationError):
        _run(request, state_schema_version="edit-run-state.v1")


@pytest.mark.parametrize(
    "changes",
    [
        {"target_track_id": UUID(int=9)},
        {"start_bar": 2},
        {"end_bar": 15},
        {"start_bar": 0},
        {"end_bar": 17},
    ],
)
def test_append_requires_exact_full_source_and_no_target(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PianoSemanticRequest(intent="增加伴奏", mode="append", **changes)


@pytest.mark.parametrize(
    "start,end,target",
    [
        (1, 5, UUID(int=9)),
        (4, 3, UUID(int=9)),
        (1, 4, None),
    ],
)
def test_modify_rejects_missing_target_or_more_than_four_bars(
    start: int, end: int, target: UUID | None
) -> None:
    with pytest.raises(ValidationError):
        PianoSemanticRequest(
            intent="更轻", mode="modify", target_track_id=target, start_bar=start, end_bar=end
        )


def test_modify_selection_and_intent_cannot_disagree_with_authorized_request() -> None:
    track_id = UUID(int=9)
    semantic = PianoSemanticRequest(
        intent="更轻", mode="modify", target_track_id=track_id, start_bar=9, end_bar=12
    )
    selection = Selection(track_ids=(track_id,), start_tick=8 * 1920, end_tick=12 * 1920)
    request = EditRunRequest(intent=semantic.intent, selection=selection, piano_request=semantic)
    assert _run(request).state_schema_version == "piano-accompaniment-run.v1"
    for mismatched in (
        Selection(track_ids=(UUID(int=10),), start_tick=8 * 1920, end_tick=12 * 1920),
        Selection(track_ids=(track_id,), start_tick=7 * 1920, end_tick=12 * 1920),
        Selection(track_ids=(track_id,)),
    ):
        with pytest.raises(ValidationError):
            EditRunRequest(intent=semantic.intent, selection=mismatched, piano_request=semantic)
    with pytest.raises(ValidationError):
        EditRunRequest(intent="修改原谱", selection=selection, piano_request=semantic)
    append = PianoSemanticRequest(intent="增加伴奏", mode="append")
    with pytest.raises(ValidationError):
        EditRunRequest(intent=append.intent, selection=selection, piano_request=append)
