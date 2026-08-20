from uuid import uuid4

from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.ir import NoteClip, TrackRole
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
    assert "aligned transitions" in next(
        issue for issue in classical.issues if issue.rule_id == "CLA-101"
    ).evidence.measured_fact
    assert "strong-beat guide tones" in next(
        issue for issue in jazz.issues if issue.rule_id == "JAZ-101"
    ).evidence.measured_fact
    assert not classical.blocking
    assert not jazz.blocking


def test_jazz_avoid_note_warning_points_to_the_actual_strong_beat() -> None:
    arrangement = build_s1_composition(uuid4(), seed=10).arrangement
    tracks = []
    for track in arrangement.tracks:
        if track.role is not TrackRole.MELODY:
            tracks.append(track)
            continue
        clips = []
        changed = False
        for clip in track.clips:
            if not isinstance(clip, NoteClip) or not clip.notes or changed:
                clips.append(clip)
                continue
            notes = (clip.notes[0].model_copy(update={"pitch": 65}), *clip.notes[1:])
            clips.append(clip.model_copy(update={"notes": notes}))
            changed = True
        tracks.append(track.model_copy(update={"clips": tuple(clips)}))
    arrangement = arrangement.model_copy(update={"tracks": tuple(tracks)})

    report = TheoryEngine().evaluate(
        arrangement,
        builtin_style_pack_registry().resolve("jazz_harmony_improvisation"),
    )

    warning = next(issue for issue in report.issues if issue.rule_id == "JAZ-102")
    assert warning.severity is TheorySeverity.WARNING
    assert warning.evidence.bars[0] == 0
    assert "unresolved fourths" in warning.evidence.measured_fact
