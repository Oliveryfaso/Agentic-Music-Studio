from __future__ import annotations

from uuid import uuid4

from motif_forge.agent.schemas import CompositionPlan
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V1,
    PLAN_HASH_VERSION_V2,
    PersistedCompositionPlan,
    canonical_plan_json_bytes,
    composition_plan_content_hash,
)


def _plan(*, energy: float, confidence: float) -> CompositionPlan:
    return CompositionPlan.model_validate(
        {
            "schema_version": "composition-plan.v1",
            "genre": "synth_ambient",
            "era_influences": (),
            "purpose": "Instrumental deterministic hash fixture",
            "moods": ("calm",),
            "duration_bars": 8,
            "bpm": 64,
            "meter": "4/4",
            "key": {"tonic": "C", "mode": "major"},
            "sections": (
                {
                    "section_id": "opening",
                    "name": "Opening",
                    "start_bar": 0,
                    "end_bar": 4,
                    "function": "Open",
                    "energy": energy,
                },
                {
                    "section_id": "ending",
                    "name": "Ending",
                    "start_bar": 4,
                    "end_bar": 8,
                    "function": "Close",
                    "energy": 0.2,
                },
            ),
            "instrumentation": tuple(
                {
                    "instrument_id": role,
                    "name": role.title(),
                    "role": role,
                    "pitch_range": "supported",
                    "entry_section_id": "opening",
                    "exit_section_id": "ending",
                }
                for role in ("pad", "melody", "bass", "rhythm")
            ),
            "harmonic_language": "diatonic",
            "rhythmic_language": "sparse",
            "texture": "layered",
            "hard_constraints": (),
            "soft_preferences": (),
            "negative_constraints": (),
            "knowledge_references": (),
            "confidence": confidence,
        },
        strict=True,
    )


def test_plan_hash_round_trips_exact_validated_execution_facts() -> None:
    plan = _plan(energy=0.2500001, confidence=0.9000001)
    reloaded = CompositionPlan.model_validate_json(canonical_plan_json_bytes(plan), strict=True)

    assert reloaded == plan
    assert composition_plan_content_hash(reloaded) == composition_plan_content_hash(plan)


def test_plan_hash_distinguishes_sub_micro_float_differences() -> None:
    below = _plan(energy=0.2499999, confidence=0.8999999)
    above = _plan(energy=0.2500001, confidence=0.9000001)

    assert canonical_plan_json_bytes(below) != canonical_plan_json_bytes(above)
    assert composition_plan_content_hash(below) != composition_plan_content_hash(above)


def test_legacy_hash_version_still_verifies_rounded_plan_identity() -> None:
    below = _plan(energy=0.2499999, confidence=0.8999999)
    above = _plan(energy=0.2500001, confidence=0.9000001)
    legacy_hash = composition_plan_content_hash(below, hash_version=PLAN_HASH_VERSION_V1)

    assert legacy_hash == composition_plan_content_hash(
        above, hash_version=PLAN_HASH_VERSION_V1
    )
    persisted = PersistedCompositionPlan(
        plan_id=uuid4(),
        run_id=uuid4(),
        plan=below,
        content_hash=legacy_hash,
        hash_version=PLAN_HASH_VERSION_V1,
        provider="fallback",
        model="deterministic",
        prompt_version="p1",
        schema_version="composition-plan.v1",
        style_pack_version="synth-ambient.v1",
    )
    assert persisted.hash_version == PLAN_HASH_VERSION_V1


def test_new_persisted_plans_default_to_lossless_hash_v2() -> None:
    plan = _plan(energy=0.2500001, confidence=0.9000001)
    persisted = PersistedCompositionPlan(
        plan_id=uuid4(),
        run_id=uuid4(),
        plan=plan,
        content_hash=composition_plan_content_hash(plan),
        provider="fallback",
        model="deterministic",
        prompt_version="p1",
        schema_version="composition-plan.v1",
        style_pack_version="synth-ambient.v1",
    )
    assert persisted.hash_version == PLAN_HASH_VERSION_V2
