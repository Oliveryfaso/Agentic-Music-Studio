from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import UUID

import pytest
from motif_forge.agent.edit import BoundedEditContext, FallbackEditPlanner
from motif_forge.application.errors import ApplicationError
from motif_forge.domain.ai_runs import EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.editing import LockedRangeRef, simulate_edit_patch
from motif_forge.domain.errors import DomainValidationError
from motif_forge.domain.ir import ArrangementIR, Section, Track, TrackRole, TrackType
from motif_forge.domain.revisions import ChangeImpact

EVAL_PATH = Path(__file__).parent / "fixtures" / "s6_edit_cases.v1.json"


def uid(value: int) -> UUID:
    return UUID(int=value)


def base() -> ArrangementIR:
    return ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=3840, label="A"),),
        tracks=(Track(
            track_id=uid(3), track_type=TrackType.INSTRUMENT,
            name="Pad", role=TrackRole.HARMONY,
        ),),
    )


def cases() -> list[dict[str, object]]:
    return json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]


def test_s6_eval_has_twelve_versioned_representative_cases() -> None:
    loaded = cases()
    assert len(loaded) == 12
    assert len({item["id"] for item in loaded}) == 12
    assert Counter(item["measurement"] for item in loaded) == {
        "deterministic": 9, "postgres": 2, "runtime_only": 1,
    }


@pytest.mark.asyncio
async def test_s6_no_key_fallback_measures_supported_routes_and_rejection() -> None:
    planner = FallbackEditPlanner()
    measured = [item for item in cases() if item["kind"] == "fallback"]
    results: dict[str, tuple[str, str | int]] = {}
    for case in measured:
        request = EditRunRequest(
            intent=str(case["intent"]),
            selection=Selection(track_ids=(uid(3),), start_tick=0, end_tick=1920),
        )
        context = BoundedEditContext.from_arrangement(base(), request).model_copy(
            update={"branch_id": uid(4), "base_revision_id": uid(5)}
        )
        try:
            proposal = await planner(context)
            simulation = simulate_edit_patch(base(), proposal)
            route = (
                "preview"
                if simulation.actual_change_impact >= ChangeImpact.L2
                else "auto_commit"
            )
            results[str(case["id"])] = (route, simulation.actual_change_impact.name)
        except ApplicationError as error:
            results[str(case["id"])] = ("error", error.code)
    assert results == {
        "s6-catalog-timbre": ("preview", "L2"),
        "s6-fallback-supported": ("auto_commit", "L0"),
        "s6-fallback-unsupported": ("error", "EDIT_FALLBACK_UNSUPPORTED"),
    }


@pytest.mark.asyncio
async def test_s6_locked_range_is_measured_from_actual_simulation() -> None:
    request = EditRunRequest(
        intent="把这里的 Pad 降低 2 dB",
        selection=Selection(track_ids=(uid(3),), start_tick=0, end_tick=1920),
        locked_ranges=(LockedRangeRef(track_id=uid(3), start_tick=960, end_tick=2880),),
    )
    context = BoundedEditContext.from_arrangement(base(), request).model_copy(
        update={"branch_id": uid(4), "base_revision_id": uid(5)}
    )
    proposal = await FallbackEditPlanner()(context)
    with pytest.raises(DomainValidationError) as captured:
        simulate_edit_patch(base(), proposal)
    assert {issue.code for issue in captured.value.issues} == {"LOCKED_RANGE_VIOLATION"}


def test_s6_metrics_exclude_runtime_only_audio_judgment() -> None:
    loaded = cases()
    measured = [item for item in loaded if item["measurement"] != "runtime_only"]
    runtime_only = [item for item in loaded if item["measurement"] == "runtime_only"]
    assert len(measured) == 11
    assert [item["id"] for item in runtime_only] == ["s6-new-accompaniment"]
    assert all("passed" not in item for item in runtime_only)
