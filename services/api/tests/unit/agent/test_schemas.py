import json

import pytest
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from pydantic import ValidationError

from .sample_data import valid_brief_payload, valid_plan_payload


def test_strict_brief_accepts_valid_json() -> None:
    brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)

    assert brief.duration_seconds == 120
    assert brief.style == "synth_ambient"


def test_brief_rejects_unknown_and_coerced_values() -> None:
    payload = valid_brief_payload()
    payload["duration_seconds"] = "120"
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        CompositionBrief.model_validate_json(json.dumps(payload), strict=True)


def test_plan_requires_contiguous_sections() -> None:
    payload = valid_plan_payload()
    payload["sections"][1]["start_bar"] = 9

    with pytest.raises(ValidationError, match="contiguous"):
        CompositionPlan.model_validate_json(json.dumps(payload), strict=True)


def test_plan_rejects_unknown_instrument_section() -> None:
    payload = valid_plan_payload()
    payload["instrumentation"][0]["exit_section_id"] = "missing"

    with pytest.raises(ValidationError, match="not in sections"):
        CompositionPlan.model_validate_json(json.dumps(payload), strict=True)
