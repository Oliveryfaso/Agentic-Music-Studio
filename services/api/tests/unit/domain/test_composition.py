from __future__ import annotations

from uuid import UUID

import pytest
from motif_forge.domain.canonical import canonical_json_bytes
from motif_forge.domain.commands import (
    InitializeCompositionCommand,
    apply_commands,
)
from motif_forge.domain.composition import (
    BarRange,
    MidiRegister,
    PatternRole,
    PatternSpec,
    build_s1_composition,
    validate_s1_arrangement,
)
from motif_forge.domain.ir import NoteClip, TrackRole, create_empty_arrangement
from motif_forge.domain.policies import command_change_impact
from motif_forge.domain.revisions import ChangeImpact
from pydantic import ValidationError

PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")


def test_pattern_spec_v1_is_strict_and_bounded() -> None:
    pattern = PatternSpec(
        pattern_id=UUID("20000000-0000-4000-8000-000000000001"),
        section_id=UUID("30000000-0000-4000-8000-000000000001"),
        track_role=PatternRole.MELODY,
        bar_range=BarRange(start_bar=0, end_bar=4),
        chord_degrees=(1, 6, 4, 5),
        rhythm_grid=(0, 4, 8, 12),
        register=MidiRegister(low_midi=60, high_midi=84),
        density=0.5,
        syncopation=0.25,
        variation_seed=7,
        locked_constraints=("key:c-major", "meter:4/4"),
    )

    assert pattern.schema_version == "pattern-spec.v1"
    assert pattern.model_dump(mode="json")["register"] == {"low_midi": 60, "high_midi": 84}
    with pytest.raises(ValidationError):
        PatternSpec.model_validate(
            {**pattern.model_dump(mode="python"), "rhythm_grid": (0, 16)}, strict=True
        )
    with pytest.raises(ValidationError):
        MidiRegister(low_midi=72, high_midi=60)


def test_s1_composer_builds_complete_audited_four_track_arrangement() -> None:
    build = build_s1_composition(PROJECT_ID, seed=20260812)

    assert build.schema_version == "composition-build.v1"
    assert build.content_hash == "b73283de2c2a57f70abccfd0ece2546d16fda5f2cfb40c699b4ce1eb3056779b"
    assert len(canonical_json_bytes(build.arrangement)) == 52196
    assert len(build.patterns) == 16
    assert isinstance(build.commands[0], InitializeCompositionCommand)
    assert command_change_impact(build.commands[0]) is ChangeImpact.L3
    assert len(build.arrangement.sections) == 4
    assert len(build.arrangement.tracks) == 4
    assert build.arrangement.duration_tick == 24 * 4 * 480
    assert build.duration_seconds == pytest.approx(72.0)
    assert {track.role for track in build.arrangement.tracks} == {
        TrackRole.HARMONY,
        TrackRole.MELODY,
        TrackRole.BASS,
        TrackRole.RHYTHM,
    }
    assert all(len(track.clips) == 4 for track in build.arrangement.tracks)
    assert all(
        isinstance(clip, NoteClip) for track in build.arrangement.tracks for clip in track.clips
    )
    assert validate_s1_arrangement(build.arrangement) == ()

    replayed = apply_commands(create_empty_arrangement(PROJECT_ID), build.commands)
    assert replayed == build.arrangement


def test_s1_composer_is_repeatable_and_seed_changes_material_not_form() -> None:
    first = build_s1_composition(PROJECT_ID, seed=17)
    repeated = build_s1_composition(PROJECT_ID, seed=17)
    varied = build_s1_composition(PROJECT_ID, seed=18)

    assert first.arrangement == repeated.arrangement
    assert first.content_hash == repeated.content_hash
    assert first.content_hash != varied.content_hash
    assert first.arrangement.sections == varied.arrangement.sections
    assert [track.instrument_ref for track in first.arrangement.tracks] == [
        track.instrument_ref for track in varied.arrangement.tracks
    ]


def test_s1_validator_reports_role_range_and_structure_failures() -> None:
    build = build_s1_composition(PROJECT_ID, seed=19)
    melody = next(track for track in build.arrangement.tracks if track.role is TrackRole.MELODY)
    first_clip = melody.clips[0]
    assert isinstance(first_clip, NoteClip)
    bad_note = first_clip.notes[0].model_copy(update={"pitch": 40})
    bad_clip = first_clip.model_copy(update={"notes": (bad_note, *first_clip.notes[1:])})
    bad_track = melody.model_copy(update={"clips": (bad_clip, *melody.clips[1:])})
    bad_arrangement = build.arrangement.model_copy(
        update={
            "tracks": tuple(
                bad_track if track.track_id == melody.track_id else track
                for track in build.arrangement.tracks
            )
        }
    )

    issues = validate_s1_arrangement(bad_arrangement)

    assert any(item.code == "S1_MELODY_RANGE_INVALID" for item in issues)
