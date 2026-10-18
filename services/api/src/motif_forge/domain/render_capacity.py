"""render-capacity.v1: bounded raw-media allocation, independent of music semantics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

POLICY_VERSION = "render-capacity.v1"
MAX_OUTPUT_BYTES = 96 * 1024**2
MAX_WORKING_BUFFER_BYTES = 320 * 1024**2
MAX_RENDER_EVENTS = 20_000


@dataclass(frozen=True, slots=True)
class RenderCapacity:
    wav_bytes: int
    output_limit_bytes: int
    working_buffer_bytes: int


def estimate_render_capacity(
    graph: dict[str, Any], *, bit_depth: int = 24, tail_seconds: float = 0.0
) -> RenderCapacity:
    """Tail is explicit; v1 callers pass zero, never the reverb decay parameter.

    The working bound covers float32 PCM and two encoded WAV buffers. It is a
    raw-media allocation bound, not an operating-system RSS guarantee.
    """
    duration = graph.get("durationSeconds")
    sample_rate = graph.get("sampleRate")
    channels = graph.get("channels")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError("RENDER_CAPACITY_INVALID")
    if (
        not math.isfinite(duration)
        or type(tail_seconds) not in {int, float}
        or not math.isfinite(tail_seconds)
        or not 0 <= tail_seconds <= 8
        or not 0.1 <= duration <= 300
        or duration + tail_seconds > 300
        or type(sample_rate) is not int
        or sample_rate not in {44_100, 48_000}
        or type(channels) is not int
        or channels != 2
        or type(bit_depth) is not int
        or bit_depth not in {16, 24}
    ):
        raise ValueError("RENDER_CAPACITY_INVALID")
    tracks = graph.get("tracks", [])
    if not isinstance(tracks, (list, tuple)) or not 1 <= len(tracks) <= 12:
        raise ValueError("RENDER_RESOURCE_LIMIT_EXCEEDED")
    events = 0
    for track in tracks:
        if not isinstance(track, dict) or track.get("kind") not in {"synth", "sampler"}:
            raise ValueError("RENDER_CAPACITY_INVALID")
        values = track.get("notes" if track["kind"] == "synth" else "triggers")
        if not isinstance(values, (list, tuple)):
            raise ValueError("RENDER_CAPACITY_INVALID")
        events += len(values)
    if events > MAX_RENDER_EVENTS:
        raise ValueError("RENDER_RESOURCE_LIMIT_EXCEEDED")
    frames = math.ceil((duration + tail_seconds) * sample_rate)
    wav_bytes = 44 + frames * channels * (bit_depth // 8)
    working = frames * channels * 4 + 2 * wav_bytes
    if wav_bytes > MAX_OUTPUT_BYTES or working > MAX_WORKING_BUFFER_BYTES:
        raise ValueError("RENDER_RESOURCE_LIMIT_EXCEEDED")
    return RenderCapacity(wav_bytes, max(1_048_576, wav_bytes), working)
