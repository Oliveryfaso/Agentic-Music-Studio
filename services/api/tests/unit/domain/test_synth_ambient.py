from __future__ import annotations

import re
from collections.abc import Callable
from uuid import UUID

import pytest
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.domain.ai_runs import (
    canonical_plan_json_bytes,
    composition_plan_content_hash,
)
from motif_forge.domain.composition import (
    PatternRole,
    SynthAmbientCompilationError,
    compile_synth_ambient_plan,
)
from motif_forge.domain.ir import NoteClip, TrackRole
from motif_forge.domain.synth_ambient import (
    SYNTH_AMBIENT_POLICY_VERSION,
    validate_synth_ambient_plan,
)
from pydantic import ValidationError

PROJECT_ID = UUID("40000000-0000-4000-8000-000000000004")


def _brief_payload() -> dict[str, object]:
    return {
        "schema_version": "composition-brief.v1",
        "title": "Polar Current",
        "purpose": "Instrumental underscore for a quiet orbital observatory",
        "style": "synth_ambient",
        "duration_seconds": 120,
        "meter": "4/4",
        "target_bpm": 72,
        "target_key": "D dorian",
        "moods": ("weightless", "curious"),
        "preferred_instruments": (),
        "hard_constraints": (),
        "soft_preferences": (),
        "negative_constraints": ("no abrupt drop",),
    }


def _plan_payload() -> dict[str, object]:
    sections = (
        {
            "section_id": "opening",
            "name": "Opening",
            "start_bar": 0,
            "end_bar": 8,
            "function": "Establish the harmonic field",
            "energy": 0.2,
        },
        {
            "section_id": "development",
            "name": "Development",
            "start_bar": 8,
            "end_bar": 28,
            "function": "Develop the pulse and motif",
            "energy": 0.68,
        },
        {
            "section_id": "resolution",
            "name": "Resolution",
            "start_bar": 28,
            "end_bar": 36,
            "function": "Reduce density and resolve",
            "energy": 0.25,
        },
    )
    roles = ("pad", "melody", "bass", "rhythm")
    return {
        "schema_version": "composition-plan.v1",
        "genre": "synth_ambient",
        "era_influences": ("modern ambient",),
        "purpose": "Instrumental underscore for a quiet orbital observatory",
        "moods": ("weightless", "curious"),
        "duration_bars": 36,
        "bpm": 72,
        "meter": "4/4",
        "key": {"tonic": "D", "mode": "dorian"},
        "sections": sections,
        "instrumentation": tuple(
            {
                "instrument_id": f"layer_{role}",
                "name": role.title(),
                "role": role,
                "pitch_range": "supported built-in range",
                "entry_section_id": "opening",
                "exit_section_id": "resolution",
            }
            for role in roles
        ),
        "harmonic_language": "Open modal harmony with restrained movement",
        "rhythmic_language": "Sparse pulses with gradual subdivision",
        "texture": "Layered synthesis with controlled tails",
        "hard_constraints": (),
        "soft_preferences": (),
        "negative_constraints": ("no abrupt drop",),
        "knowledge_references": (),
        "confidence": 0.9,
    }


def _brief(**updates: object) -> CompositionBrief:
    return CompositionBrief.model_validate({**_brief_payload(), **updates}, strict=True)


def _plan(**updates: object) -> CompositionPlan:
    return CompositionPlan.model_validate({**_plan_payload(), **updates}, strict=True)


def _instrumentation(*roles: str) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "instrument_id": f"layer_{index}_{role}",
            "name": role.title(),
            "role": role,
            "pitch_range": "supported built-in range",
            "entry_section_id": "opening",
            "exit_section_id": "resolution",
        }
        for index, role in enumerate(roles)
    )


@pytest.mark.parametrize(
    ("brief_factory", "plan_factory", "expected_rule", "expected_code"),
    (
        (
            lambda: _brief(style="minimal_electronic"),
            lambda: _plan(),
            "SAP-001",
            "STYLE_MISMATCH",
        ),
        (
            lambda: _brief(meter="3/4", duration_seconds=90),
            lambda: _plan(meter="3/4"),
            "SAP-002",
            "METER_NOT_IMPLEMENTED",
        ),
        (
            lambda: _brief(duration_seconds=90),
            lambda: _plan(),
            "SAP-003",
            "DURATION_MISMATCH",
        ),
        (
            lambda: _brief(),
            lambda: _plan(instrumentation=_instrumentation("pad", "melody", "bass")),
            "SAP-004",
            "ROLE_COVERAGE_INVALID",
        ),
        (
            lambda: _brief(),
            lambda: _plan(
                instrumentation=_instrumentation("pad", "melody", "bass", "rhythm", "pad")
            ),
            "SAP-004",
            "ROLE_COVERAGE_INVALID",
        ),
        (
            lambda: _brief(),
            lambda: _plan(negative_constraints=()),
            "SAP-008",
            "NEGATIVE_CONSTRAINT_MISSING",
        ),
        (
            lambda: _brief(target_bpm=80),
            lambda: _plan(),
            "SAP-009",
            "BPM_MISMATCH",
        ),
        (
            lambda: _brief(target_key="E minor"),
            lambda: _plan(),
            "SAP-010",
            "KEY_MISMATCH",
        ),
    ),
)
def test_policy_rejects_each_incompatible_boundary(
    brief_factory: Callable[[], CompositionBrief],
    plan_factory: Callable[[], CompositionPlan],
    expected_rule: str,
    expected_code: str,
) -> None:
    result = validate_synth_ambient_plan(brief_factory(), plan_factory())

    assert result.compatible is False
    assert result.policy_version == "synth-ambient-plan-policy.v1"
    assert [(issue.rule_id, issue.code) for issue in result.issues] == [
        (expected_rule, expected_code)
    ]


def test_duration_tolerance_accepts_larger_of_one_bar_or_ten_percent() -> None:
    one_bar_seconds = 60 * 4 / 72
    brief = _brief(duration_seconds=100)

    within_ten_percent = _plan(duration_bars=33, sections=(
        {**_plan_payload()["sections"][0]},  # type: ignore[index]
        {**_plan_payload()["sections"][1], "end_bar": 25},  # type: ignore[index]
        {**_plan_payload()["sections"][2], "start_bar": 25, "end_bar": 33},  # type: ignore[index]
    ))
    above_tolerance = _plan(duration_bars=26, sections=(
        {**_plan_payload()["sections"][0]},  # type: ignore[index]
        {**_plan_payload()["sections"][1], "end_bar": 18},  # type: ignore[index]
        {**_plan_payload()["sections"][2], "start_bar": 18, "end_bar": 26},  # type: ignore[index]
    ))

    assert one_bar_seconds < brief.duration_seconds * 0.1
    assert validate_synth_ambient_plan(brief, within_ten_percent).compatible is True
    assert "DURATION_MISMATCH" in [
        issue.code for issue in validate_synth_ambient_plan(brief, above_tolerance).issues
    ]


@pytest.mark.parametrize(
    ("duration_bars", "bpm", "duration_seconds", "expected_codes"),
    (
        (50, 40, 300, ()),
        (51, 40, 300, ("COMPILED_DURATION_UNSUPPORTED",)),
        (128, 220, 140, ()),
        (129, 220, 141, ("TOTAL_BAR_RANGE_UNSUPPORTED",)),
    ),
)
def test_policy_enforces_exact_compiler_duration_and_bar_range_boundaries(
    duration_bars: int,
    bpm: int,
    duration_seconds: int,
    expected_codes: tuple[str, ...],
) -> None:
    section_count = (duration_bars + 31) // 32
    section_ends = tuple(min(duration_bars, (index + 1) * 32) for index in range(section_count))
    section_starts = (0, *section_ends[:-1])
    sections = tuple(
        {
            "section_id": f"part_{index}",
            "name": f"Part {index}",
            "start_bar": start,
            "end_bar": end,
            "function": "Bounded deterministic section",
            "energy": 0.5,
        }
        for index, (start, end) in enumerate(zip(section_starts, section_ends, strict=True))
    )
    plan = _plan(
        duration_bars=duration_bars,
        bpm=bpm,
        sections=sections,
        instrumentation=tuple(
            item.model_copy(
                update={
                    "entry_section_id": "part_0",
                    "exit_section_id": f"part_{section_count - 1}",
                }
            )
            for item in _plan().instrumentation
        ),
    )

    result = validate_synth_ambient_plan(
        _brief(duration_seconds=duration_seconds, target_bpm=bpm), plan
    )

    assert tuple(issue.code for issue in result.issues) == expected_codes


@pytest.mark.parametrize(
    ("field", "below", "above"),
    (
        ("energy", 0.2499999, 0.2500001),
        ("confidence", 0.8999999, 0.9000001),
    ),
)
def test_plan_hash_is_lossless_for_compiler_float_facts(
    field: str, below: float, above: float
) -> None:
    baseline = _plan()
    if field == "energy":
        low = baseline.model_copy(
            update={
                "sections": (
                    baseline.sections[0].model_copy(update={"energy": below}),
                    *baseline.sections[1:],
                )
            }
        )
        high = baseline.model_copy(
            update={
                "sections": (
                    baseline.sections[0].model_copy(update={"energy": above}),
                    *baseline.sections[1:],
                )
            }
        )
    else:
        low = baseline.model_copy(update={"confidence": below})
        high = baseline.model_copy(update={"confidence": above})

    assert canonical_plan_json_bytes(low) != canonical_plan_json_bytes(high)
    assert composition_plan_content_hash(low) != composition_plan_content_hash(high)


def test_confidence_is_an_execution_fact_in_key_map() -> None:
    brief, baseline = _brief(), _plan()
    lower = baseline.model_copy(update={"confidence": 0.8999999})
    higher = baseline.model_copy(update={"confidence": 0.9000001})

    low_build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=lower, seed=14)
    high_build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=higher, seed=14)

    assert low_build.arrangement.key_map[0].confidence == 0.8999999
    assert high_build.arrangement.key_map[0].confidence == 0.9000001
    assert low_build.content_hash != high_build.content_hash


def test_equal_plan_hash_and_seed_always_produce_identical_execution_facts() -> None:
    brief, plan = _brief(), _plan()
    first = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=plan, seed=84)
    reloaded = CompositionPlan.model_validate_json(canonical_plan_json_bytes(plan), strict=True)
    repeated = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=reloaded, seed=84)

    assert composition_plan_content_hash(plan) == composition_plan_content_hash(reloaded)
    assert first.commands == repeated.commands
    assert first.content_hash == repeated.content_hash


def test_policy_issues_are_stable_and_rule_ordered() -> None:
    result = validate_synth_ambient_plan(
        _brief(style="minimal_electronic", target_bpm=80, target_key="E minor"),
        _plan(instrumentation=_instrumentation("texture"), negative_constraints=()),
    )

    assert result.policy_version == SYNTH_AMBIENT_POLICY_VERSION
    assert [issue.rule_id for issue in result.issues] == [
        "SAP-001",
        "SAP-004",
        "SAP-008",
        "SAP-009",
        "SAP-010",
    ]


def test_policy_returns_combined_failures_in_unique_declared_rule_order() -> None:
    long_sections = (
        {
            "section_id": "opening",
            "name": "Opening",
            "start_bar": 0,
            "end_bar": 36,
            "function": "Long development",
            "energy": 0.5,
        },
        {
            "section_id": "resolution",
            "name": "Resolution",
            "start_bar": 36,
            "end_bar": 40,
            "function": "Resolve",
            "energy": 0.2,
        },
    )
    result = validate_synth_ambient_plan(
        _brief(style="minimal_electronic", target_bpm=80, target_key="E minor"),
        _plan(
            duration_bars=40,
            sections=long_sections,
            instrumentation=tuple(
                {**item, "entry_section_id": "opening", "role": "texture"}
                for item in _instrumentation("pad")
            ),
            negative_constraints=(),
        ),
    )

    assert [(issue.rule_id, issue.code) for issue in result.issues] == [
        ("SAP-001", "STYLE_MISMATCH"),
        ("SAP-003", "DURATION_MISMATCH"),
        ("SAP-004", "ROLE_COVERAGE_INVALID"),
        ("SAP-005", "SECTION_LENGTH_UNSUPPORTED"),
        ("SAP-008", "NEGATIVE_CONSTRAINT_MISSING"),
        ("SAP-009", "BPM_MISMATCH"),
        ("SAP-010", "KEY_MISMATCH"),
    ]


def test_policy_fails_closed_when_roles_have_no_supported_mapping() -> None:
    unmapped = _instrumentation("pad", "melody", "bass", "rhythm")
    unmapped = tuple(
        {**item, "role": role}
        for item, role in zip(unmapped, ("harmonic bed", "lead", "low end", "pulse"), strict=True)
    )
    result = validate_synth_ambient_plan(
        _brief(),
        _plan(instrumentation=unmapped),
    )

    assert result.compatible is False
    assert [(issue.rule_id, issue.code) for issue in result.issues] == [
        ("SAP-004", "ROLE_COVERAGE_INVALID")
    ]


def test_policy_rejects_a_section_too_long_for_pattern_spec_v1() -> None:
    sections = (
        {
            "section_id": "opening",
            "name": "Opening",
            "start_bar": 0,
            "end_bar": 36,
            "function": "Long development",
            "energy": 0.5,
        },
        {
            "section_id": "resolution",
            "name": "Resolution",
            "start_bar": 36,
            "end_bar": 40,
            "function": "Resolve",
            "energy": 0.2,
        },
    )
    plan = _plan(
        duration_bars=40,
        bpm=40,
        sections=sections,
        instrumentation=tuple(
            item.model_copy(update={"entry_section_id": "opening"})
            for item in _plan().instrumentation
        ),
    )

    result = validate_synth_ambient_plan(
        _brief(duration_seconds=240, target_bpm=40), plan
    )

    assert [(issue.rule_id, issue.code) for issue in result.issues] == [
        ("SAP-005", "SECTION_LENGTH_UNSUPPORTED")
    ]


@pytest.mark.parametrize("tonic", ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"))
@pytest.mark.parametrize(
    "mode", ("major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "locrian")
)
def test_policy_and_compiler_admit_all_twelve_tonics_and_seven_modes(
    tonic: str, mode: str
) -> None:
    plan = _plan(key={"tonic": tonic, "mode": mode})
    brief = _brief(target_key=f"{tonic} {mode}")

    assert validate_synth_ambient_plan(brief, plan).compatible is True
    build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=plan, seed=19)
    assert build.arrangement.key_map[0].mode.value == mode
    assert all(
        0 <= note.pitch <= 127
        for track in build.arrangement.tracks
        for clip in track.clips
        if isinstance(clip, NoteClip)
        for note in clip.notes
    )


def test_compiler_is_deterministic_and_replays_existing_commands() -> None:
    brief, plan = _brief(), _plan()

    first = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=plan, seed=20260813)
    repeated = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=plan, seed=20260813)

    assert first.commands == repeated.commands
    assert first.arrangement == repeated.arrangement
    assert first.content_hash == repeated.content_hash
    assert len(first.patterns) == len(plan.sections) * 4
    assert len(first.commands) == 5


def test_compiler_uses_plan_key_energy_and_sections_as_musical_inputs() -> None:
    brief, baseline = _brief(), _plan()
    energized_sections = tuple(
        section.model_copy(update={"energy": 0.95}) for section in baseline.sections
    )
    resectioned = _plan(
        duration_bars=36,
        sections=(
            {
                "section_id": "arrival",
                "name": "Arrival",
                "start_bar": 0,
                "end_bar": 12,
                "function": "Establish",
                "energy": 0.2,
            },
            {
                "section_id": "orbit",
                "name": "Orbit",
                "start_bar": 12,
                "end_bar": 36,
                "function": "Develop and resolve",
                "energy": 0.6,
            },
        ),
        instrumentation=tuple(
            item.model_copy(update={"entry_section_id": "arrival", "exit_section_id": "orbit"})
            for item in baseline.instrumentation
        ),
    )

    base_build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=baseline, seed=77)
    energy_build = compile_synth_ambient_plan(
        PROJECT_ID,
        brief=brief,
        plan=baseline.model_copy(update={"sections": energized_sections}),
        seed=77,
    )
    key_build = compile_synth_ambient_plan(
        PROJECT_ID,
        brief=brief.model_copy(update={"target_key": None}),
        plan=baseline.model_copy(update={"key": baseline.key.model_copy(update={"tonic": "E"})}),
        seed=77,
    )
    section_build = compile_synth_ambient_plan(
        PROJECT_ID, brief=brief, plan=resectioned, seed=77
    )

    assert base_build.patterns != energy_build.patterns
    assert base_build.patterns != key_build.patterns
    assert base_build.patterns != section_build.patterns
    assert len(base_build.arrangement.sections) != len(section_build.arrangement.sections)
    assert len(base_build.arrangement.tracks[0].clips) != len(
        section_build.arrangement.tracks[0].clips
    )
    assert len(base_build.arrangement.tracks[1].clips[1].notes) < len(
        energy_build.arrangement.tracks[1].clips[1].notes
    )
    base_pitches = tuple(
        note.pitch
        for clip in base_build.arrangement.tracks[1].clips
        for note in clip.notes
    )
    key_pitches = tuple(
        note.pitch
        for clip in key_build.arrangement.tracks[1].clips
        for note in clip.notes
    )
    assert base_pitches != key_pitches
    assert base_build.patterns[1].rhythm_grid != energy_build.patterns[1].rhythm_grid
    assert base_build.content_hash != key_build.content_hash


def test_energy_threshold_changes_density_syncopation_rhythm_and_note_count() -> None:
    brief, baseline = _brief(), _plan()
    below = baseline.model_copy(
        update={
            "sections": (
                baseline.sections[0].model_copy(update={"energy": 0.2499999}),
                *baseline.sections[1:],
            )
        }
    )
    above = baseline.model_copy(
        update={
            "sections": (
                baseline.sections[0].model_copy(update={"energy": 0.2500001}),
                *baseline.sections[1:],
            )
        }
    )

    low_build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=below, seed=18)
    high_build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=above, seed=18)
    low_melody = next(
        pattern
        for pattern in low_build.patterns
        if pattern.section_id == low_build.arrangement.sections[0].section_id
        and pattern.track_role is PatternRole.MELODY
    )
    high_melody = next(
        pattern
        for pattern in high_build.patterns
        if pattern.section_id == high_build.arrangement.sections[0].section_id
        and pattern.track_role is PatternRole.MELODY
    )
    low_clip = low_build.arrangement.tracks[1].clips[0]
    high_clip = high_build.arrangement.tracks[1].clips[0]

    assert low_melody.density == pytest.approx(below.sections[0].energy * 0.8 + 0.15)
    assert high_melody.density == pytest.approx(above.sections[0].energy * 0.8 + 0.15)
    assert low_melody.syncopation == pytest.approx(below.sections[0].energy * 0.3)
    assert high_melody.syncopation == pytest.approx(above.sections[0].energy * 0.3)
    assert low_melody.rhythm_grid != high_melody.rhythm_grid
    assert len(low_clip.notes) != len(high_clip.notes)


def test_compiler_outputs_a_bounded_complete_four_track_arrangement() -> None:
    brief, plan = _brief(), _plan()
    build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=plan, seed=99)

    assert build.duration_seconds == pytest.approx(plan.duration_bars * 4 * 60 / plan.bpm)
    assert build.arrangement.duration_tick == plan.duration_bars * 4 * 480
    assert len(build.arrangement.tracks) == 4
    assert {track.role for track in build.arrangement.tracks} == {
        TrackRole.HARMONY,
        TrackRole.MELODY,
        TrackRole.BASS,
        TrackRole.RHYTHM,
    }
    assert {pattern.track_role for pattern in build.patterns} == set(PatternRole)
    assert all(
        clip.start_tick + clip.duration_tick <= build.arrangement.duration_tick
        and all(note.start_tick + note.duration_tick <= clip.duration_tick for note in clip.notes)
        for track in build.arrangement.tracks
        for clip in track.clips
        if isinstance(clip, NoteClip)
    )
    assert any(
        ref.kind == "knowledge"
        and ref.ref == f"composition-plan:{composition_plan_content_hash(plan)}"
        for ref in build.arrangement.provenance
    )
    assert all(ref.kind != "model" for ref in build.arrangement.provenance)
    assert any(
        ref.kind == "engine" and ref.ref == "deterministic-seed:99"
        for ref in build.arrangement.provenance
    )


def test_instrument_entry_and_exit_sections_control_actual_clip_presence() -> None:
    plan = _plan()
    delayed = plan.model_copy(
        update={
            "instrumentation": tuple(
                item.model_copy(
                    update={
                        "entry_section_id": "development",
                        "exit_section_id": "development",
                    }
                )
                if item.role == "melody"
                else item
                for item in plan.instrumentation
            )
        }
    )

    build = compile_synth_ambient_plan(PROJECT_ID, brief=_brief(), plan=delayed, seed=22)
    melody = next(track for track in build.arrangement.tracks if track.role is TrackRole.MELODY)

    assert len(melody.clips) == 1
    assert melody.clips[0].start_tick == 8 * 4 * 480
    assert melody.clips[0].duration_tick == 20 * 4 * 480
    assert all(len(track.clips) == 3 for track in build.arrangement.tracks if track is not melody)


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    (("Db", "C#"), ("Eb", "D#"), ("Gb", "F#"), ("Ab", "G#"), ("Bb", "A#")),
)
def test_enharmonic_schema_keys_normalize_to_canonical_ir_pitch_class(
    spelling: str, canonical: str
) -> None:
    plan = _plan(key={"tonic": spelling, "mode": "dorian"})
    brief = _brief(target_key=f"{spelling} dorian")

    build = compile_synth_ambient_plan(PROJECT_ID, brief=brief, plan=plan, seed=24)

    assert build.arrangement.key_map[0].tonic == canonical
    assert build.arrangement.key_map[0].mode.value == "dorian"


def test_compiler_rechecks_authoritative_brief_before_creating_commands() -> None:
    incompatible_brief = _brief(
        duration_seconds=90,
        target_bpm=80,
        target_key="E minor",
        negative_constraints=("no abrupt drop", "no pulse"),
    )

    with pytest.raises(SynthAmbientCompilationError) as captured:
        compile_synth_ambient_plan(
            PROJECT_ID, brief=incompatible_brief, plan=_plan(), seed=12
        )

    assert tuple(issue.code for issue in captured.value.issues) == (
        "DURATION_MISMATCH",
        "NEGATIVE_CONSTRAINT_MISSING",
        "BPM_MISMATCH",
        "KEY_MISMATCH",
    )


def test_compiler_projects_long_plan_section_function_into_ir_bound() -> None:
    long_function = (
        "Establishes a slowly unfolding modal field while introducing a restrained pulse "
        "and preserving the weightless, curious entrance."
    )
    sections = tuple(
        {**section, "function": long_function}
        if section["section_id"] == "opening"
        else section
        for section in _plan_payload()["sections"]  # type: ignore[union-attr]
    )
    plan = _plan(sections=sections)

    build = compile_synth_ambient_plan(PROJECT_ID, brief=_brief(), plan=plan, seed=25)

    assert plan.sections[0].function == long_function
    assert build.arrangement.sections[0].function == long_function[:80]
    assert len(build.arrangement.sections[0].function) == 80


@pytest.mark.parametrize(
    ("plan", "seed", "expected_code"),
    (
        (
            _plan(genre="minimal_electronic"),
            1,
            "STYLE_MISMATCH",
        ),
        (
            _plan(instrumentation=_instrumentation("pad", "melody", "bass")),
            1,
            "ROLE_COVERAGE_INVALID",
        ),
        (
            _plan(),
            -1,
            "seed must be between 0 and 2^31-1",
        ),
        (
            _plan(
                duration_bars=40,
                bpm=40,
                sections=(
                    {
                        "section_id": "opening",
                        "name": "Opening",
                        "start_bar": 0,
                        "end_bar": 36,
                        "function": "Long development",
                        "energy": 0.5,
                    },
                    {
                        "section_id": "resolution",
                        "name": "Resolution",
                        "start_bar": 36,
                        "end_bar": 40,
                        "function": "Resolve",
                        "energy": 0.2,
                    },
                ),
                instrumentation=tuple(
                    item.model_copy(update={"entry_section_id": "opening"})
                    for item in _plan().instrumentation
                ),
            ),
            1,
            "SECTION_LENGTH_UNSUPPORTED",
        ),
    ),
)
def test_compiler_fails_closed_outside_its_validated_contract(
    plan: CompositionPlan, seed: int, expected_code: str
) -> None:
    if seed < 0:
        with pytest.raises(ValueError, match=re.escape(expected_code)):
            compile_synth_ambient_plan(
                PROJECT_ID,
                brief=_brief(),
                plan=plan,
                seed=seed,
            )
        return
    with pytest.raises(SynthAmbientCompilationError) as captured:
        compile_synth_ambient_plan(
            PROJECT_ID,
            brief=_brief(target_bpm=None, target_key=None, negative_constraints=()),
            plan=plan,
            seed=seed,
        )
    assert expected_code in {issue.code for issue in captured.value.issues}


def test_generic_plan_schema_rejects_noncontiguous_sections_before_policy() -> None:
    sections = list(_plan_payload()["sections"])  # type: ignore[arg-type]
    sections[1] = {**sections[1], "start_bar": 9}

    with pytest.raises(ValidationError, match="sections must be ordered, contiguous"):
        _plan(sections=tuple(sections))
