import json

from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.schemas import CompositionBrief

from .sample_data import valid_brief_payload


def test_fallback_plan_is_complete_low_confidence_and_deterministic() -> None:
    brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)

    first = build_fallback_plan(brief)
    second = build_fallback_plan(brief)

    assert first == second
    assert first.confidence == 0.35
    assert first.sections[0].start_bar == 0
    assert first.sections[-1].end_bar == first.duration_bars
    assert first.knowledge_references == ()
