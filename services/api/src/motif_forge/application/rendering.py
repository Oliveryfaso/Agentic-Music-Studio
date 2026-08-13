"""One-way ArrangementIR to versioned AudioGraphSpec render projection."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from motif_forge.domain.ir import ArrangementIR, DomainModel, NoteClip, Track, TrackRole
from motif_forge.domain.media_jobs import (
    CanonicalRenderJobPayload,
    MediaQualityProfile,
    RenderScope,
)
from motif_forge.domain.revisions import Revision
from motif_forge.domain.timebase import ticks_to_seconds

AUDIO_GRAPH_SCHEMA_VERSION = "audio-graph-spec.v1"
AUDIO_ENGINE_VERSION: Literal["motif-forge-audio-engine.v1"] = "motif-forge-audio-engine.v1"


class AudioGraphProjection(DomainModel):
    schema_version: Literal["audio-graph-projection.v1"] = "audio-graph-projection.v1"
    arrangement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_track_ids: tuple[UUID, ...]
    graph: dict[str, Any]


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seconds(tick: int, bpm: float, ppq: int) -> float:
    return round(float(ticks_to_seconds(tick, bpm=str(bpm), ppq=ppq)), 6)


def _track_spec(track: Track, *, bpm: float, ppq: int) -> dict[str, object]:
    base: dict[str, object] = {
        "trackId": str(track.track_id),
        "name": track.name,
        "gainDb": track.gain_db,
        "pan": track.pan,
        "eq": {
            "lowDb": track.eq.low_db,
            "midDb": track.eq.mid_db,
            "highDb": track.eq.high_db,
        },
        "reverbSend": 0.26 if track.role in {TrackRole.HARMONY, TrackRole.MELODY} else 0.05,
    }
    notes = [
        {
            "midi": note.pitch,
            "startSeconds": _seconds(clip.start_tick + note.start_tick, bpm, ppq),
            "durationSeconds": _seconds(note.duration_tick, bpm, ppq),
            "velocity": round(note.velocity / 127, 6),
        }
        for clip in track.clips
        if isinstance(clip, NoteClip)
        for note in clip.notes
    ]
    if any(not isinstance(clip, NoteClip) for clip in track.clips):
        raise ValueError("AUDIO_TRACK_RENDER_UNSUPPORTED")
    if track.instrument_ref == "builtin:click":
        return {
            **base,
            "kind": "sampler",
            "sampleId": "builtin:click",
            "sampleUrl": "/assets/builtin-click.wav",
            "triggers": [
                {"startSeconds": note["startSeconds"], "gain": note["velocity"]} for note in notes
            ],
        }
    preset_by_ref = {
        "builtin:warm_pad": "warm_pad",
        "builtin:glass_pluck": "glass_pluck",
        "builtin:sub_bass": "sub_bass",
    }
    preset_id = preset_by_ref.get(track.instrument_ref or "")
    if preset_id is None:
        raise ValueError("INSTRUMENT_REF_UNSUPPORTED")
    return {**base, "kind": "synth", "presetId": preset_id, "notes": notes}


def compile_audio_graph(
    arrangement: ArrangementIR, *, render_track_ids: tuple[UUID, ...] | None = None
) -> AudioGraphProjection:
    """Project immutable tick truth to one canonical render-only seconds graph."""

    from motif_forge.domain.canonical import arrangement_content_hash

    all_ids = tuple(track.track_id for track in arrangement.tracks)
    selected_ids = all_ids if render_track_ids is None else render_track_ids
    if len(set(selected_ids)) != len(selected_ids) or any(
        item not in all_ids for item in selected_ids
    ):
        raise ValueError("RENDER_SCOPE_INVALID")
    selected = tuple(track for track in arrangement.tracks if track.track_id in selected_ids)
    bpm = arrangement.tempo_map[0].bpm
    graph = {
        "schemaVersion": AUDIO_GRAPH_SCHEMA_VERSION,
        "engineVersion": AUDIO_ENGINE_VERSION,
        "durationSeconds": _seconds(arrangement.duration_tick, bpm, arrangement.ppq),
        "sampleRate": arrangement.sample_rate,
        "channels": 2,
        "masterGainDb": -5.0,
        "reverbDecaySeconds": 2.4,
        "tracks": [
            _track_spec(track, bpm=bpm, ppq=arrangement.ppq)
            for track in sorted(selected, key=lambda item: str(item.track_id))
        ],
    }
    return AudioGraphProjection(
        arrangement_hash=arrangement_content_hash(arrangement),
        graph_hash=_canonical_hash(graph),
        render_track_ids=selected_ids,
        graph=graph,
    )


def build_canonical_render_payload(
    revision: Revision,
    *,
    seed: int,
    render_track_ids: tuple[UUID, ...] = (),
) -> CanonicalRenderJobPayload:
    """Reloaded Revision truth is the only input to a canonical render request."""

    projection = compile_audio_graph(
        revision.arrangement_ir,
        render_track_ids=render_track_ids or None,
    )
    scope = RenderScope.STEM if render_track_ids else RenderScope.MASTER
    quality: Literal[
        MediaQualityProfile.CANONICAL_MASTER_V1,
        MediaQualityProfile.CANONICAL_STEM_V1,
    ] = (
        MediaQualityProfile.CANONICAL_STEM_V1
        if render_track_ids
        else MediaQualityProfile.CANONICAL_MASTER_V1
    )
    if projection.arrangement_hash != revision.content_hash:
        raise ValueError("REVISION_ARRANGEMENT_HASH_MISMATCH")
    return CanonicalRenderJobPayload(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        render_scope=scope,
        render_track_ids=render_track_ids,
        quality_profile=quality,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version=AUDIO_ENGINE_VERSION,
        seed=seed,
        timeout_seconds=240,
        maximum_output_bytes=64 * 1024 * 1024,
    )
