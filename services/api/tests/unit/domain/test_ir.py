from __future__ import annotations

from uuid import UUID

import pytest
from motif_forge.domain import (
    ArrangementIR,
    KeyPoint,
    MusicalMode,
    NoteClip,
    NoteEvent,
    Section,
    Track,
    TrackRole,
    TrackType,
    arrangement_content_hash,
    canonical_json_bytes,
)
from pydantic import ValidationError


def uid(value: int) -> UUID:
    return UUID(int=value)


def make_track(track_id: int = 10, clip_id: int = 20, note_id: int = 30) -> Track:
    return Track(
        track_id=uid(track_id),
        track_type=TrackType.INSTRUMENT,
        name=f"Track {track_id}",
        role=TrackRole.MELODY,
        clips=(
            NoteClip(
                clip_id=uid(clip_id),
                start_tick=0,
                duration_tick=1_920,
                notes=(
                    NoteEvent(
                        note_id=uid(note_id),
                        pitch=60,
                        start_tick=0,
                        duration_tick=480,
                    ),
                ),
            ),
        ),
    )


def make_arrangement(*tracks: Track) -> ArrangementIR:
    return ArrangementIR(
        project_id=uid(1),
        sections=(
            Section(
                section_id=uid(2),
                start_tick=0,
                end_tick=3_840,
                label="A",
            ),
        ),
        key_map=(
            KeyPoint(
                tick=0,
                tonic="C",
                mode=MusicalMode.MAJOR,
                confidence=1.0,
                source="user",
            ),
        ),
        tracks=tracks,
    )


def test_minimum_arrangement_is_valid_and_uses_v1_time_contract() -> None:
    arrangement = make_arrangement(make_track())

    assert arrangement.ppq == 480
    assert arrangement.sample_rate == 48_000
    assert arrangement.duration_tick == 3_840
    assert arrangement.bar_ticks == 1_920
    assert arrangement.tracks[0].clips[0].clip_type == "note"


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"ppq": 960}, "Input should be 480"),
        ({"sample_rate": 32_000}, "Input should be 44100, 48000 or 96000"),
        (
            {"sections": (Section(section_id=uid(3), start_tick=1, end_tick=1_921, label="bad"),)},
            "sections must start at tick 0",
        ),
    ],
)
def test_arrangement_rejects_invalid_global_ranges(
    updates: dict[str, object], message: str
) -> None:
    data = make_arrangement().model_dump(mode="python")
    data.update(updates)

    with pytest.raises(ValidationError, match=message):
        ArrangementIR.model_validate(data)


def test_clip_and_note_must_remain_in_bounds() -> None:
    with pytest.raises(ValidationError, match="note must remain within its clip"):
        NoteClip(
            clip_id=uid(20),
            start_tick=0,
            duration_tick=480,
            notes=(
                NoteEvent(
                    note_id=uid(30),
                    pitch=60,
                    start_tick=240,
                    duration_tick=480,
                ),
            ),
        )

    outside_track = make_track().model_copy(
        update={"clips": (NoteClip(clip_id=uid(21), start_tick=3_000, duration_tick=1_000),)}
    )
    with pytest.raises(ValidationError, match="clip must remain within arrangement bounds"):
        make_arrangement(outside_track)


def test_canonical_hash_is_stable_across_collection_order_and_float_noise() -> None:
    first_track = make_track(10, 20, 30)
    second_track = make_track(11, 21, 31)
    first = make_arrangement(first_track, second_track)
    second_data = first.model_dump(mode="python")
    second_data["tracks"] = (second_track, first_track)
    second = ArrangementIR.model_validate(second_data)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert arrangement_content_hash(first) == arrangement_content_hash(second)
    assert len(arrangement_content_hash(first)) == 64


def test_domain_models_are_frozen() -> None:
    arrangement = make_arrangement(make_track())

    with pytest.raises(ValidationError, match="Instance is frozen"):
        arrangement.ppq = 960  # type: ignore[misc]
