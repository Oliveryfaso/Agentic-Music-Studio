from pathlib import Path
from uuid import UUID

import pytest
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import apply_commands
from motif_forge.domain.ir import (
    ArrangementIRV3,
    LockedRange,
    NoteClip,
    NotePerformance,
    PerformancePlan,
    ProvenanceRef,
)
from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan
from pydantic import ValidationError

DATA = Path(__file__).parents[3] / "src/motif_forge/resources/scores/ode-melody.musicxml"
PROJECT = UUID(int=528)
REQUEST = UUID(int=2201)


def source():
    return score_to_arrangement(
        parse_musicxml(DATA.read_bytes(), namespace=PROJECT),
        project_id=PROJECT,
        source_ref="score:mutopia-528-melody.v1",
    )


def plan(start=1, end=16, *, grid=(0, 4, 8, 12), octave=2, velocity=54):
    return AccompanimentPlan(
        summary="保留旋律, 低音区钢琴伴奏",
        bars=tuple(
            BarPlan(bar=bar, chord="G", grid=grid, octave=octave, velocity=velocity)
            for bar in range(start, end + 1)
        ),
    )


def two_parts():
    base = source()
    command = accompaniment_command(
        base,
        AccompanimentIntent(pattern="broken", chords=("G",) * 16),
        request_id=UUID(int=2200),
    )
    value = apply_commands(base, (command,))
    assert isinstance(value, ArrangementIRV3)
    return value


def test_append_compiles_exact_rhythm_triad_rotation_and_replay_without_mutating_source():
    base = source()
    before = arrangement_content_hash(base)
    bars = tuple(
        BarPlan(
            bar=bar,
            chord="G",
            grid=(0,) if bar <= 8 else (0, 4, 8, 12),
            octave=2,
            velocity=48 if bar <= 8 else 64,
        )
        for bar in range(1, 17)
    )
    semantic = AccompanimentPlan(summary="前半稀疏、后半稍活跃", bars=bars)
    track = compile_piano_plan(base, semantic, request_id=REQUEST)
    assert track == compile_piano_plan(base, semantic, request_id=REQUEST)
    assert arrangement_content_hash(base) == before
    assert track.instrument_ref == "builtin:jazz-piano" and track.role.value == "bass"
    assert track.gain_db == -10.0 and not track.locked_ranges
    clip = track.clips[0]
    assert isinstance(clip, NoteClip)
    assert clip.start_tick == 0 and clip.duration_tick == base.duration_tick
    assert len([note for note in clip.notes if note.start_tick < 8 * 1920]) == 8
    assert len([note for note in clip.notes if note.start_tick >= 8 * 1920]) == 32
    assert [note.pitch for note in clip.notes[8:12]] == [43, 47, 50, 47]
    assert [note.start_tick for note in clip.notes[8:12]] == [15360, 15840, 16320, 16800]
    assert all(note.duration_tick == 360 for note in clip.notes)
    assert max(note.start_tick + note.duration_tick for note in clip.notes) < 16 * 1920
    assert all(21 <= note.pitch <= 108 for note in clip.notes)


def test_local_edit_preserves_track_clip_metadata_and_exact_notes_outside_selected_bars():
    base = two_parts()
    original = base.tracks[0]
    target = base.tracks[1].model_copy(update={"name": "我的伴奏", "pan": -0.2, "gain_db": -13.0})
    unsorted_clip = target.clips[0]
    assert isinstance(unsorted_clip, NoteClip)
    unsorted_clip = unsorted_clip.model_copy(
        update={"notes": (unsorted_clip.notes[1], unsorted_clip.notes[0], *unsorted_clip.notes[2:])}
    )
    target = target.model_copy(update={"clips": (unsorted_clip,)})
    base = base.model_copy(update={"tracks": (original, target)})
    old_clip = target.clips[0]
    assert isinstance(old_clip, NoteClip)
    edited = compile_piano_plan(
        base,
        plan(9, 12, grid=(0,), octave=3, velocity=36),
        request_id=REQUEST,
        target_track_id=target.track_id,
        start_bar=9,
        end_bar=12,
    )
    clip = edited.clips[0]
    assert isinstance(clip, NoteClip)

    def outside(note):
        return not 8 * 1920 <= note.start_tick < 12 * 1920

    assert tuple(filter(outside, clip.notes)) == tuple(filter(outside, old_clip.notes))
    assert all(
        new is old
        for new, old in zip(
            filter(outside, clip.notes), filter(outside, old_clip.notes), strict=True
        )
    )
    assert edited.model_dump(exclude={"clips"}) == target.model_dump(exclude={"clips"})
    assert clip.model_dump(exclude={"notes"}) == old_clip.model_dump(exclude={"notes"})
    inside = [note for note in clip.notes if not outside(note)]
    assert len(inside) == 4 and all(note.velocity == 36 and note.pitch == 55 for note in inside)
    assert not {note.note_id for note in inside} & {note.note_id for note in old_clip.notes}
    assert base.tracks[0] == original and base.tracks[1] == target


@pytest.mark.parametrize("grid", [(0, 0), (4, 0), (-1,), (16,), tuple(range(9)), ()])
def test_plan_rejects_invalid_or_unbounded_grid(grid):
    with pytest.raises(ValidationError):
        BarPlan(bar=1, chord="G", grid=grid, octave=2, velocity=54)


def test_schema_rejects_cross_bar_gate_and_extra_model_authority():
    with pytest.raises(ValidationError, match="ACCOMPANIMENT_NOTE_OUT_OF_BAR"):
        BarPlan(bar=1, chord="G", grid=(15,), octave=2, velocity=54, gate_steps=2)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        BarPlan(bar=1, chord="G", grid=(0,), octave=2, velocity=54, track_id="model-owned")
    assert BarPlan(bar=1, chord="G", grid=(15,), octave=2, velocity=54, gate_steps=1)


@pytest.mark.parametrize("bars", [(1,), tuple(range(1, 16)), (*range(1, 16), 15)])
def test_append_rejects_partial_duplicate_or_missing_measure_plan(bars):
    partial = AccompanimentPlan(
        summary="不完整",
        bars=tuple(BarPlan(bar=bar, chord="G", grid=(0,), octave=2, velocity=54) for bar in bars),
    )
    with pytest.raises(ValueError, match="ACCOMPANIMENT_BAR_COVERAGE"):
        compile_piano_plan(source(), partial, request_id=REQUEST)


def test_source_contract_rejects_unknown_provenance_unlocked_melody_and_wrong_key():
    base = source()
    variants = (
        base.model_copy(update={"provenance": ()}),
        base.model_copy(
            update={
                "provenance": (
                    ProvenanceRef(
                        kind="asset", ref="score:mutopia-528-melody.v1", version="0" * 64
                    ),
                )
            }
        ),
        base.model_copy(
            update={"tracks": (base.tracks[0].model_copy(update={"locked_ranges": ()}),)}
        ),
        base.model_copy(update={"key_map": (base.key_map[0].model_copy(update={"tonic": "C"}),)}),
    )
    for unknown in variants:
        with pytest.raises(ValueError, match="CLASSICAL_SOURCE_REQUIRED"):
            compile_piano_plan(unknown, plan(), request_id=REQUEST)


def test_modify_rejects_original_track_locks_wide_range_and_wrong_track_count():
    base = two_parts()
    target = base.tracks[1]
    for candidate, track_id, first, last in (
        (base, base.tracks[0].track_id, 9, 12),
        (base, target.track_id, 8, 12),
        (base, target.track_id, 0, 3),
        (base, target.track_id, 15, 18),
        (base, UUID(int=999), 9, 12),
        (
            base.model_copy(
                update={
                    "tracks": (*base.tracks, target.model_copy(update={"track_id": UUID(int=999)}))
                }
            ),
            target.track_id,
            9,
            12,
        ),
        (
            base.model_copy(
                update={
                    "tracks": (
                        base.tracks[0],
                        target.model_copy(
                            update={"locked_ranges": (LockedRange(start_tick=0, end_tick=1920),)}
                        ),
                    )
                }
            ),
            target.track_id,
            9,
            12,
        ),
    ):
        with pytest.raises(ValueError, match=r"ACCOMPANIMENT_(SCOPE_INVALID|TARGET_INVALID)"):
            compile_piano_plan(
                candidate,
                plan(9, 12),
                request_id=REQUEST,
                target_track_id=track_id,
                start_bar=first,
                end_bar=last,
            )
    with pytest.raises(ValueError, match="ACCOMPANIMENT_SCOPE_INVALID"):
        compile_piano_plan(base, plan(), request_id=REQUEST)
    with pytest.raises(ValueError, match="ACCOMPANIMENT_SCOPE_INVALID"):
        compile_piano_plan(source(), plan(1, 4), request_id=REQUEST, start_bar=1, end_bar=4)


def test_modify_rejects_replacing_note_with_performance_override_but_retains_outside_override():
    base = two_parts()
    target = base.tracks[1]
    clip = target.clips[0]
    assert isinstance(clip, NoteClip)
    for index, rejected in ((0, False), (32, True)):
        override = NotePerformance(
            track_id=target.track_id,
            clip_id=clip.clip_id,
            note_id=clip.notes[index].note_id,
            velocity_override=40,
        )
        performed = base.model_copy(update={"performance_plan": PerformancePlan(notes=(override,))})
        if rejected:
            with pytest.raises(ValueError, match="ACCOMPANIMENT_PERFORMANCE_CONFLICT"):
                compile_piano_plan(
                    performed,
                    plan(9, 12),
                    request_id=REQUEST,
                    target_track_id=target.track_id,
                    start_bar=9,
                    end_bar=12,
                )
        else:
            result = compile_piano_plan(
                performed,
                plan(9, 12),
                request_id=REQUEST,
                target_track_id=target.track_id,
                start_bar=9,
                end_bar=12,
            )
            assert clip.notes[0] in result.clips[0].notes
            assert performed.performance_plan.notes == (override,)


def test_modify_rejects_existing_notes_that_cross_selection_boundary():
    base = two_parts()
    target = base.tracks[1]
    clip = target.clips[0]
    assert isinstance(clip, NoteClip)
    crossing = clip.notes[31].model_copy(update={"duration_tick": 600})
    updated_clip = clip.model_copy(update={"notes": (*clip.notes[:31], crossing, *clip.notes[32:])})
    updated = base.model_copy(
        update={"tracks": (base.tracks[0], target.model_copy(update={"clips": (updated_clip,)}))}
    )
    with pytest.raises(ValueError, match="ACCOMPANIMENT_SCOPE_INVALID"):
        compile_piano_plan(
            updated,
            plan(9, 12),
            request_id=REQUEST,
            target_track_id=target.track_id,
            start_bar=9,
            end_bar=12,
        )
