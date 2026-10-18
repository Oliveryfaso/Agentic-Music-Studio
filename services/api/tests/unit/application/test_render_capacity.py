from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from motif_forge.application.rendering import (
    build_candidate_preview_payload,
    build_canonical_render_payload,
)
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.ir import (
    ArrangementIR,
    NoteClip,
    NoteEvent,
    Section,
    Track,
    TrackType,
)
from motif_forge.domain.revisions import create_candidate_snapshot, create_root_state


def arrangement(seconds: float) -> ArrangementIR:
    ticks = round(seconds * 960)
    return ArrangementIR(
        project_id=UUID(int=42),
        sections=(Section(section_id=UUID(int=43), start_tick=0, end_tick=ticks, label="A"),),
        tracks=(
            Track(
                track_id=UUID(int=44),
                track_type=TrackType.INSTRUMENT,
                name="Legacy pad",
                instrument_ref="builtin:warm_pad",
                clips=(
                    NoteClip(
                        clip_id=UUID(int=45),
                        start_tick=0,
                        duration_tick=ticks,
                        notes=(
                            NoteEvent(
                                note_id=UUID(int=46),
                                pitch=60,
                                start_tick=0,
                                duration_tick=min(ticks, 480),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def revision(seconds: float):
    value = arrangement(seconds)
    return create_root_state(value.project_id, created_by="p1:test").revision.model_copy(
        update={"arrangement_ir": value, "content_hash": arrangement_content_hash(value)}
    )


@pytest.mark.parametrize(
    "seconds,want", [(2, 1_048_576), (30, 8_640_044), (72, 20_736_044), (300, 86_400_044)]
)
def test_canonical_budget_covers_pcm24_without_reserving_a_fixed_64_mib(seconds, want):
    payload = build_canonical_render_payload(revision(seconds), seed=42)
    assert payload.maximum_output_bytes == want


def test_preview_budget_covers_five_minute_pcm_intermediate_not_mp3_size():
    base = revision(300)
    snapshot = create_candidate_snapshot(
        base_revision=base,
        candidate_ir=base.arrangement_ir,
        candidate_id=UUID(int=47),
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
    )
    payload = build_candidate_preview_payload(snapshot, seed=42)
    assert payload.maximum_output_bytes == 86_400_044


def test_capacity_fix_does_not_extend_legacy_render_duration_or_change_engine():
    payload = build_canonical_render_payload(revision(30), seed=42)
    assert payload.audio_graph["durationSeconds"] == 30
    assert payload.audio_engine_version == "motif-forge-audio-engine.v1"
    assert payload.schema_version == "canonical-render-job.v1"


def test_capacity_policy_refuses_more_than_five_minutes_before_queueing():
    with pytest.raises(ValueError, match="RENDER_CAPACITY_INVALID"):
        build_canonical_render_payload(revision(302), seed=42)


def test_capacity_policy_refuses_unbounded_event_allocations_before_queueing():
    base = revision(300)
    track = base.arrangement_ir.tracks[0]
    clip = track.clips[0]
    notes = tuple(
        NoteEvent(note_id=UUID(int=100 + i), pitch=60, start_tick=0, duration_tick=1)
        for i in range(20_001)
    )
    changed = base.arrangement_ir.model_copy(
        update={
            "tracks": (
                track.model_copy(update={"clips": (clip.model_copy(update={"notes": notes}),)}),
            )
        }
    )
    base = base.model_copy(
        update={"arrangement_ir": changed, "content_hash": arrangement_content_hash(changed)}
    )
    with pytest.raises(ValueError, match="RENDER_RESOURCE_LIMIT_EXCEEDED"):
        build_canonical_render_payload(base, seed=42)


@pytest.mark.parametrize(
    "seconds,rate,depth,tail,want",
    [
        (30, 48000, 24, 0, 8_640_044),
        (300, 48000, 24, 0, 86_400_044),
        (30, 44100, 16, 2, 5_644_844),
        (0.10001, 48000, 24, 0, 28_850),
    ],
)
def test_raw_capacity_accounts_for_format_rounding_and_explicit_tail(
    seconds, rate, depth, tail, want
):
    from motif_forge.domain.render_capacity import estimate_render_capacity

    graph = build_canonical_render_payload(revision(2), seed=42).audio_graph.copy()
    graph.update(durationSeconds=seconds, sampleRate=rate)
    result = estimate_render_capacity(graph, bit_depth=depth, tail_seconds=tail)
    assert result.wav_bytes == want
    assert result.working_buffer_bytes <= 320 * 1024**2


@pytest.mark.parametrize(
    "overrides,tail",
    [
        ({"durationSeconds": float("nan")}, 0),
        ({"durationSeconds": 300}, 1),
        ({"channels": 1}, 0),
        ({"sampleRate": 96000}, 0),
    ],
)
def test_invalid_capacity_is_rejected_before_allocation(overrides, tail):
    from motif_forge.domain.render_capacity import estimate_render_capacity

    graph = build_canonical_render_payload(revision(2), seed=42).audio_graph.copy()
    graph.update(overrides)
    with pytest.raises(ValueError, match="RENDER_CAPACITY_INVALID"):
        estimate_render_capacity(graph, tail_seconds=tail)
