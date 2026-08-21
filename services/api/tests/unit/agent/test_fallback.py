import json

from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.domain.synth_ambient import validate_synth_ambient_plan

from .sample_data import valid_brief_payload


def test_fallback_plan_is_complete_low_confidence_and_deterministic() -> None:
    brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)

    first = build_fallback_plan(brief)
    second = build_fallback_plan(brief)

    assert first == second
    assert first.confidence == 0.35
    assert first.sections[0].start_bar == 0
    assert first.sections[-1].end_bar == first.duration_bars
    assert first.knowledge_references[0].reference_id == "style:synth-ambient:v1"
    assert first.knowledge_references[0].confidence == 1.0


def test_synth_ambient_fallback_is_compilation_safe() -> None:
    brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)

    plan = build_fallback_plan(brief)

    assert tuple(item.role for item in plan.instrumentation) == (
        "pad",
        "melody",
        "bass",
        "rhythm",
    )
    assert validate_synth_ambient_plan(brief, plan).compatible is True


def test_fallback_preserves_a_sixty_second_brief_within_duration_policy() -> None:
    brief = CompositionBrief.model_validate_json(
        json.dumps(
            {
                **valid_brief_payload(),
                "duration_seconds": 60,
                "target_bpm": 72,
            }
        ),
        strict=True,
    )

    plan = build_fallback_plan(brief)

    assert plan.duration_bars == 18
    assert validate_synth_ambient_plan(brief, plan).compatible is True
