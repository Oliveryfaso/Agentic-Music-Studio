from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from motif_forge.agent.critic import (
    CriticCandidate,
    CriticRequest,
    DeterministicEvidenceCritic,
)
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.generate import CandidateSelectionDecision
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.application.candidate_repair import EvaluateCandidatePair
from motif_forge.domain.candidates import (
    CandidateEvidence,
    CandidateLabel,
    derive_candidate_seed,
    merge_candidate_branches,
)
from motif_forge.domain.music_strategies import MusicStrategyRouter

EVAL_PATH = Path(__file__).parents[4] / "evals" / "s5-candidate-critic-repair-v1.json"


def test_s5_eval_has_twelve_balanced_creative_and_recovery_cases() -> None:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 12
    assert Counter(case["style"] for case in cases if case["kind"] == "generate") == {
        "synth_ambient": 2,
        "minimal_electronic": 2,
        "classical_chamber": 2,
        "jazz_harmony_improvisation": 2,
    }
    assert {case["kind"] for case in cases if case["kind"] != "generate"} == {
        "repair_improved", "repair_non_improving", "restart_replay", "reject_cancel",
    }


def test_s5_eval_cases_freeze_bounded_candidate_facts() -> None:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        expected = case["expected"]
        assert expected["candidate_families"] == 2
        assert expected["selection_previews"] in {0, 2}
        assert expected["repair_children"] in {0, 1}
        assert expected["selected_revisions"] in {0, 1}
        assert expected["provider_requests"] == 0


@pytest.mark.asyncio
async def test_s5_generate_eval_compiles_and_criticizes_two_distinct_candidates() -> None:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]
    router = MusicStrategyRouter()
    critic = DeterministicEvidenceCritic()
    for case in (item for item in cases if item["kind"] == "generate"):
        brief = CompositionBrief(
            title=case["id"], purpose="Create a bounded instrumental candidate pair",
            style=case["style"], duration_seconds=60, meter="4/4", moods=("focused",),
        )
        candidates = []
        evidence = []
        for label in (CandidateLabel.A, CandidateLabel.B):
            seed = derive_candidate_seed(case["seed"], label)
            candidate_id = uuid5(NAMESPACE_URL, f"{case['id']}:{label.value}")
            compiled = router.compile(
                candidate_id, brief=brief, plan=build_fallback_plan(brief), seed=seed
            )
            assert not compiled.theory_report.blocking
            candidates.append(CriticCandidate(candidate_id=candidate_id, label=label))
            evidence.append(CandidateEvidence(
                evidence_ref=f"candidate:{candidate_id}:theory",
                candidate_id=candidate_id, kind="theory", severity="info",
                measured_fact="deterministic Theory report has zero blocking errors",
                score_delta=1 if label is CandidateLabel.B else 0,
            ))
        result = await critic.evaluate(CriticRequest(
            run_id=uuid5(NAMESPACE_URL, case["id"]),
            candidates=tuple(candidates), evidence=tuple(evidence),
        ))
        assert len(result.critique.assessments) == 2
        assert result.model_calls == 0


def test_s5_behavior_eval_exercises_repair_replay_and_reject_contracts() -> None:
    gate = EvaluateCandidatePair()
    original = uuid5(NAMESPACE_URL, "eval-original")
    repaired = uuid5(NAMESPACE_URL, "eval-repaired")
    assert gate(
        original_snapshot_id=original, repaired_snapshot_id=repaired,
        original_score=70, repaired_score=78,
        original_blocking_errors=0, repaired_blocking_errors=0,
    ).repair_status == "improved"
    assert gate(
        original_snapshot_id=original, repaired_snapshot_id=repaired,
        original_score=70, repaired_score=69,
        original_blocking_errors=0, repaired_blocking_errors=0,
    ).repair_status == "non_improving"
    branch = {"candidate_id": str(original), "label": "a"}
    assert merge_candidate_branches([branch], [branch]) == [branch]
    decision = CandidateSelectionDecision(
        decision="reject", actor_id="eval-human",
        selection_assertion="I reject both bounded candidates.",
    )
    assert decision.selected_preview_id is None
