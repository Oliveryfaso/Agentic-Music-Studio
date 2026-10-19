"""One-way ArrangementIR to versioned AudioGraphSpec render projection."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field

from motif_forge.domain.ir import (
    ArrangementIR,
    ArrangementIRV2,
    ArrangementIRV3,
    ArrangementIRV4,
    ArrangementIRV5,
    DomainModel,
    NoteClip,
    Track,
    TrackRole,
)
from motif_forge.domain.media_jobs import (
    CandidatePreviewJobPayload,
    CandidatePreviewJobPayloadV2,
    CandidatePreviewJobPayloadV3,
    CandidatePreviewJobPayloadV4,
    CandidatePreviewJobPayloadV5,
    CanonicalRenderJobPayload,
    CanonicalRenderJobPayloadV2,
    CanonicalRenderJobPayloadV3,
    CanonicalRenderJobPayloadV4,
    CanonicalRenderJobPayloadV5,
    MediaQualityProfile,
    RenderScope,
)
from motif_forge.domain.render_capacity import estimate_render_capacity
from motif_forge.domain.revisions import CandidateSnapshot, Revision
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
    click_refs = {
        "builtin:click",
        "builtin:drum-machine",
        "builtin:pizz-cello",
        "builtin:brush-kit",
    }
    if track.instrument_ref in click_refs:
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
        "builtin:warm-pad": "warm_pad",
        "builtin:glass_pluck": "glass_pluck",
        "builtin:glass-pluck": "glass_pluck",
        "builtin:sub_bass": "sub_bass",
        "builtin:sub-bass": "sub_bass",
        "builtin:soft-pulse": "warm_pad",
        "builtin:poly-synth": "warm_pad",
        "builtin:short-pluck": "glass_pluck",
        "builtin:mono-bass": "sub_bass",
        "builtin:viola": "warm_pad",
        "builtin:violin": "glass_pluck",
        "builtin:cello": "sub_bass",
        "builtin:jazz-piano": "warm_pad",
        "builtin:tenor-lead": "glass_pluck",
        "builtin:upright-bass": "sub_bass",
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

    if isinstance(arrangement, ArrangementIRV2):
        return _compile_piano_graph(arrangement, render_track_ids=render_track_ids)

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


def _compile_piano_graph(
    arrangement: ArrangementIRV2, *, render_track_ids: tuple[UUID, ...] | None
) -> AudioGraphProjection:
    from motif_forge.domain.canonical import arrangement_content_hash

    all_ids = tuple(track.track_id for track in arrangement.tracks)
    selected = all_ids if render_track_ids is None else render_track_ids
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(all_ids):
        raise ValueError("RENDER_SCOPE_INVALID")
    version = (
        "v5"
        if isinstance(arrangement, ArrangementIRV5)
        else "v4"
        if isinstance(arrangement, ArrangementIRV4)
        else "v3"
        if isinstance(arrangement, ArrangementIRV3)
        else "v2"
    )
    graph: dict[str, Any] = {
        "schemaVersion": "audio-graph-spec." + version,
        "engineVersion": "motif-forge-audio-engine." + version,
        "durationSeconds": _seconds(
            arrangement.duration_tick, arrangement.tempo_map[0].bpm, arrangement.ppq
        ),
        "sampleRate": 48000,
        "channels": 2,
        "masterGainDb": -5.0,
        "reverbDecaySeconds": 2.4,
        "tracks": [
            _piano_track_spec(arrangement, track)
            for track in sorted(arrangement.tracks, key=lambda t: str(t.track_id))
            if track.track_id in selected
        ],
    }
    if isinstance(arrangement, ArrangementIRV4):
        mixes = {item.track_id: item for item in arrangement.piano_mix.tracks}
        any_solo = any(item.solo for item in mixes.values())
        for track in graph["tracks"]:
            mix = mixes[UUID(track["trackId"])]
            track.update(
                gainDb=mix.gain_db, pan=mix.pan, audible=not mix.mute and (not any_solo or mix.solo)
            )
        graph["expectedSilence"] = not any(t["audible"] for t in graph["tracks"])
    if isinstance(arrangement, ArrangementIRV5):
        graph["eqProfile"] = arrangement.render_profile.eq_profile.model_dump(mode="json")
        settings = {item.track_id: item for item in arrangement.piano_eq.tracks}
        for track in graph["tracks"]:
            track["eq3"] = settings[UUID(track["trackId"])].model_dump(
                mode="json", exclude={"track_id"}
            )
    return AudioGraphProjection(
        arrangement_hash=arrangement_content_hash(arrangement),
        graph_hash=_canonical_hash(graph),
        render_track_ids=selected,
        graph=graph,
    )


def _piano_track_spec(arrangement: ArrangementIRV2, track: Track) -> dict[str, Any]:
    bpm, ppq = arrangement.tempo_map[0].bpm, arrangement.ppq
    overrides = {(p.track_id, p.clip_id, p.note_id): p for p in arrangement.performance_plan.notes}
    values = []
    for clip in track.clips:
        assert isinstance(clip, NoteClip)
        for note in clip.notes:
            performance = overrides.get((track.track_id, clip.clip_id, note.note_id))
            offset = performance.onset_offset_tick if performance else 0
            velocity = (
                performance.velocity_override
                if performance and performance.velocity_override is not None
                else note.velocity
            )
            gate = (
                performance.gate_duration_tick
                if performance and performance.gate_duration_tick is not None
                else note.duration_tick
            )
            values.append(
                (
                    clip.start_tick + note.start_tick + offset,
                    str(track.track_id),
                    str(clip.clip_id),
                    str(note.note_id),
                    {
                        "noteId": str(
                            uuid5(
                                NAMESPACE_URL,
                                f"piano:{track.track_id}:{clip.clip_id}:{note.note_id}",
                            )
                        ),
                        "midi": note.pitch,
                        "velocity": velocity,
                        "startSeconds": _seconds(
                            clip.start_tick + note.start_tick + offset, bpm, ppq
                        ),
                        "gateSeconds": _seconds(gate, bpm, ppq),
                        "detuneCents": note.cents,
                    },
                )
            )
    profile = arrangement.render_profile
    return {
        "trackId": str(track.track_id),
        "name": track.name,
        "kind": "multisample",
        "gainDb": -60.0 if track.mute else track.gain_db,
        "pan": track.pan,
        "eq": {
            "lowDb": track.eq.low_db,
            "midDb": track.eq.mid_db,
            "highDb": track.eq.high_db,
        },
        "reverbSend": 0.0,
        "instrumentPack": {
            "packId": profile.instrument_pack_id,
            "packVersion": profile.instrument_pack_version,
            "manifestSha256": profile.manifest_sha256,
        },
        "notes": [item[-1] for item in sorted(values, key=lambda v: v[:4])],
    }


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
    payload_type = (
        CanonicalRenderJobPayloadV5
        if isinstance(revision.arrangement_ir, ArrangementIRV5)
        else CanonicalRenderJobPayloadV4
        if isinstance(revision.arrangement_ir, ArrangementIRV4)
        else CanonicalRenderJobPayloadV3
        if isinstance(revision.arrangement_ir, ArrangementIRV3)
        else CanonicalRenderJobPayloadV2
        if isinstance(revision.arrangement_ir, ArrangementIRV2)
        else CanonicalRenderJobPayload
    )
    return payload_type(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        render_scope=scope,
        render_track_ids=render_track_ids,
        quality_profile=quality,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version=projection.graph["engineVersion"],
        seed=seed,
        timeout_seconds=240,
        maximum_output_bytes=estimate_render_capacity(projection.graph).output_limit_bytes,
    )


def build_candidate_preview_payload(
    snapshot: CandidateSnapshot, *, seed: int
) -> CandidatePreviewJobPayload:
    """Compile immutable CandidateSnapshot truth into a bounded audition request."""

    projection = compile_audio_graph(snapshot.candidate_ir)
    if projection.arrangement_hash != snapshot.candidate_content_hash:
        raise ValueError("CANDIDATE_ARRANGEMENT_HASH_MISMATCH")
    payload_type = (
        CandidatePreviewJobPayloadV5
        if isinstance(snapshot.candidate_ir, ArrangementIRV5)
        else CandidatePreviewJobPayloadV4
        if isinstance(snapshot.candidate_ir, ArrangementIRV4)
        else CandidatePreviewJobPayloadV3
        if isinstance(snapshot.candidate_ir, ArrangementIRV3)
        else CandidatePreviewJobPayloadV2
        if isinstance(snapshot.candidate_ir, ArrangementIRV2)
        else CandidatePreviewJobPayload
    )
    return payload_type(
        project_id=snapshot.project_id,
        candidate_snapshot_id=snapshot.candidate_snapshot_id,
        candidate_content_hash=snapshot.candidate_content_hash,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        audio_engine_version=projection.graph["engineVersion"],
        seed=seed,
        timeout_seconds=240,
        maximum_output_bytes=estimate_render_capacity(projection.graph).output_limit_bytes,
    )
