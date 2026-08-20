import json
from collections import Counter
from pathlib import Path
from uuid import UUID

import pytest
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.domain.music_strategies import MusicStrategyRouter
from motif_forge.domain.style_packs import LicenseSnapshot, builtin_style_pack_registry
from pydantic import ValidationError

EVAL_PATH = Path(__file__).parents[4] / "evals" / "s4-four-style-packs-v1.json"


def test_s4_eval_compiles_two_distinct_cases_per_style() -> None:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]
    generate = [case for case in cases if case["kind"] == "generate"]
    assert Counter(case["style"] for case in generate) == {
        "synth_ambient": 2,
        "minimal_electronic": 2,
        "classical_chamber": 2,
        "jazz_harmony_improvisation": 2,
    }
    router = MusicStrategyRouter()
    signatures = {}
    for case in generate:
        brief = CompositionBrief.model_validate(
            {
                "title": case["id"],
                "purpose": "Create a complete deterministic instrumental cue",
                "style": case["style"],
                "duration_seconds": case["duration_seconds"],
                "meter": "4/4",
                "target_key": "C major",
                "moods": ("focused",),
            },
            strict=True,
        )
        result = router.compile(
            UUID(int=case["seed"]),
            brief=brief,
            plan=build_fallback_plan(brief),
            seed=case["seed"],
        )
        assert not result.theory_report.blocking
        assert result.pack.sources[0].license_id == "project-authored"
        signatures.setdefault(case["style"], result.build.content_hash)
    assert len(set(signatures.values())) == 4


def test_s4_eval_policy_cases_fail_closed() -> None:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]
    rejects = {case["reason"] for case in cases if case["kind"] == "policy_reject"}
    assert rejects == {"unknown_style", "unreviewed_nc_license"}
    with pytest.raises(KeyError):
        builtin_style_pack_registry().resolve("unknown")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        LicenseSnapshot(
            license_id="CC-BY-NC-4.0",
            reviewed=False,
            allows_commercial_use=False,
            attribution_required=True,
        )
