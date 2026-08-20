from uuid import uuid4

from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.style_packs import builtin_style_pack_registry
from motif_forge.domain.theory import TheoryEngine, TheorySeverity


def test_engine_returns_ordered_nonblocking_evidence_for_valid_arrangement() -> None:
    arrangement = build_s1_composition(uuid4(), seed=7).arrangement
    pack = builtin_style_pack_registry().resolve("synth_ambient")

    report = TheoryEngine().evaluate(arrangement, pack)

    assert report.engine_version == "theory-engine.v1"
    assert report.blocking == ()
    assert tuple(issue.rule_id for issue in report.issues) == tuple(
        sorted(issue.rule_id for issue in report.issues)
    )
    assert all(issue.evidence.bars and issue.suggested_operation for issue in report.issues)


def test_missing_export_role_is_a_blocking_error_with_track_evidence() -> None:
    arrangement = build_s1_composition(uuid4(), seed=8).arrangement
    arrangement = arrangement.model_copy(update={"tracks": arrangement.tracks[:-1]})
    pack = builtin_style_pack_registry().resolve("synth_ambient")

    report = TheoryEngine().evaluate(arrangement, pack)

    assert len(report.blocking) == 1
    issue = report.blocking[0]
    assert issue.rule_id == "CORE-001"
    assert issue.severity is TheorySeverity.ERROR
    assert issue.explanation_code == "EXPORT_ROLE_COVERAGE_INVALID"


def test_style_specific_findings_are_measured_and_nonblocking() -> None:
    arrangement = build_s1_composition(uuid4(), seed=9).arrangement
    registry = builtin_style_pack_registry()

    classical = TheoryEngine().evaluate(arrangement, registry.resolve("classical_chamber"))
    jazz = TheoryEngine().evaluate(arrangement, registry.resolve("jazz_harmony_improvisation"))

    assert any(issue.rule_id == "CLA-101" for issue in classical.issues)
    assert any(issue.rule_id == "JAZ-101" for issue in jazz.issues)
    assert not classical.blocking
    assert not jazz.blocking
