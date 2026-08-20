from uuid import UUID, uuid4

import pytest
from motif_forge.domain.candidates import (
    CandidateAssessment,
    CandidateCritique,
    CandidateEvidence,
    CandidateFinding,
    CandidateLabel,
    derive_candidate_seed,
    merge_candidate_branches,
    project_candidate_segments,
)
from motif_forge.domain.composition import build_s1_composition

CANDIDATE_A = UUID("00000000-0000-0000-0000-00000000000a")
CANDIDATE_B = UUID("00000000-0000-0000-0000-00000000000b")


def test_candidate_seed_and_reducer_are_stable_and_order_independent() -> None:
    assert derive_candidate_seed(0, CandidateLabel.A) == 0
    assert derive_candidate_seed(0, CandidateLabel.B) == 1_048_583
    left = [{"candidate_id": str(CANDIDATE_B), "label": "b"}]
    right = [{"candidate_id": str(CANDIDATE_A), "label": "a"}]

    assert merge_candidate_branches(left, right) == [
        {"candidate_id": str(CANDIDATE_A), "label": "a"},
        {"candidate_id": str(CANDIDATE_B), "label": "b"},
    ]
    assert merge_candidate_branches(left, left) == left
    with pytest.raises(ValueError, match="two stable candidates"):
        merge_candidate_branches(
            left + right,
            [{"candidate_id": str(uuid4()), "label": "a"}],
        )


def test_segment_projection_is_acyclic_and_bounds_each_track_to_a_section() -> None:
    arrangement = build_s1_composition(uuid4(), seed=7).arrangement

    segments = project_candidate_segments(CANDIDATE_A, arrangement)

    assert len(segments) == len(arrangement.sections) * len(arrangement.tracks)
    segment_ids = {item.segment_id for item in segments}
    assert all(item.start_tick < item.end_tick for item in segments)
    assert all(set(item.depends_on) <= segment_ids for item in segments)
    assert all(item.segment_id not in item.depends_on for item in segments)
    by_id = {item.segment_id: item for item in segments}
    for item in segments:
        assert all(by_id[parent].start_tick <= item.start_tick for parent in item.depends_on)


def test_critique_rejects_findings_without_real_evidence_refs() -> None:
    evidence = CandidateEvidence(
        evidence_ref="theory:a:CORE-001",
        candidate_id=CANDIDATE_A,
        kind="theory",
        severity="warning",
        measured_fact="one measured warning",
    )
    assessment_a = CandidateAssessment(
        candidate_id=CANDIDATE_A,
        label=CandidateLabel.A,
        score=72,
        evidence_refs=(evidence.evidence_ref,),
    )
    assessment_b = CandidateAssessment(
        candidate_id=CANDIDATE_B,
        label=CandidateLabel.B,
        score=75,
        evidence_refs=(),
    )

    with pytest.raises(ValueError, match="unknown evidence"):
        CandidateCritique(
            evidence=(evidence,),
            assessments=(assessment_a, assessment_b),
            findings=(
                CandidateFinding(
                    finding_code="DENSITY_HIGH",
                    candidate_id=CANDIDATE_A,
                    severity="warning",
                    evidence_refs=("invented:evidence",),
                ),
            ),
            recommended_candidate_id=CANDIDATE_B,
            rationale="Candidate B has fewer measured issues.",
        )


def test_critique_requires_exactly_one_assessment_for_each_label() -> None:
    assessment = CandidateAssessment(
        candidate_id=CANDIDATE_A,
        label=CandidateLabel.A,
        score=80,
        evidence_refs=(),
    )
    with pytest.raises(ValueError, match="exactly candidate A and B"):
        CandidateCritique(
            evidence=(),
            assessments=(assessment, assessment),
            findings=(),
            recommended_candidate_id=CANDIDATE_A,
            rationale="Invalid duplicate labels.",
        )
