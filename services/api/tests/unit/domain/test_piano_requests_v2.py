import json
from uuid import UUID

import pytest
from motif_forge.application.piano_preview import PianoPreviewRequest
from motif_forge.domain.ai_runs import EditRunRequest
from pydantic import ValidationError


def payload(score="c01-minuet-g-a16.v1", beats=3, bars=16, **changes):
    return {
        "schema_version": "piano-semantic-request.v2",
        "source_score_id": score,
        "beats_per_bar": beats,
        "intent": "低音区疏密对比,保留旋律",
        "mode": "append",
        "start_bar": 1,
        "end_bar": bars,
        **changes,
    }


@pytest.mark.parametrize(
    "score,beats,bars",
    [
        ("c01-minuet-g-a16.v1", 3, 16),
        ("c02-la-candeur-a8.v1", 4, 8),
        ("j01-bethena-a-first8.v1", 3, 8),
    ],
)
def test_new_sources_roundtrip_explicit_v2_scope(score, beats, bars):
    data = {
        name: str(UUID(int=i + 1))
        for i, name in enumerate(["project_id", "branch_id", "base_revision_id", "request_id"])
    }
    data["semantic"] = payload(score, beats, bars)
    request = PianoPreviewRequest.model_validate_json(json.dumps(data), strict=True)
    assert request.semantic.model_dump(mode="json") == data["semantic"] | {"target_track_id": None}
    assert (
        PianoPreviewRequest.model_validate_json(request.model_dump_json(), strict=True) == request
    )


def test_three_four_edit_selection_uses_actual_ticks_and_rejects_four_four_scope():
    semantic = payload(
        "j01-bethena-a-first8.v1",
        3,
        8,
        mode="modify",
        target_track_id=str(UUID(int=9)),
        start_bar=5,
    )
    body = {
        "intent": semantic["intent"],
        "piano_request": semantic,
        "selection": {"track_ids": [str(UUID(int=9))], "start_tick": 5760, "end_tick": 11520},
    }
    parsed = EditRunRequest.model_validate_json(json.dumps(body), strict=True)
    assert parsed.selection.start_tick == 4 * 3 * 480
    body["selection"]["start_tick"] = 7680
    body["selection"]["end_tick"] = 15360
    with pytest.raises(ValidationError):
        EditRunRequest.model_validate_json(json.dumps(body), strict=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"beats_per_bar": 4},
        {"end_bar": 9},
        {"end_bar": 7},
        {"source_score_id": "mutopia-528-melody.v1"},
        {"mode": "modify"},
    ],
)
def test_new_scope_rejects_mismatched_meter_coverage_source_or_missing_target(changes):
    data = {
        name: str(UUID(int=i + 1))
        for i, name in enumerate(["project_id", "branch_id", "base_revision_id", "request_id"])
    }
    data["semantic"] = payload("j01-bethena-a-first8.v1", 3, 8, **changes)
    with pytest.raises(ValidationError):
        PianoPreviewRequest.model_validate_json(json.dumps(data), strict=True)
