"""Lightweight deterministic BPM/key analysis for normalized PCM audio.

This is intentionally a dependency-free first-release baseline.  It is designed to
produce conservative confidence values and route ambiguous material to HITL, not to
pretend to replace a specialist music-information-retrieval stack.
"""

from __future__ import annotations

import math
import struct
import wave
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast

from motif_forge.domain.media_jobs import ImportedAudioAnalysis

IMPORT_ANALYSIS_VERSION = "import-analysis.v1"
_MAX_ANALYSIS_SECONDS = 120
_ENVELOPE_HZ = 100

_MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
_TONICS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def analyze_imported_audio(path: Path) -> ImportedAudioAnalysis:
    """Analyze a bounded prefix of one normalized mono/stereo PCM16 WAV."""

    samples, sample_rate = _read_mono_prefix(path)
    bpm, bpm_confidence = _estimate_bpm(samples, sample_rate)
    tonic, mode, key_confidence = _estimate_key(samples, sample_rate)
    return ImportedAudioAnalysis(
        analysis_version="import-analysis.v1",
        bpm=bpm,
        bpm_confidence=bpm_confidence,
        key_tonic=tonic,
        key_mode=mode,
        key_confidence=key_confidence,
        analyzed_seconds=min(len(samples) / sample_rate, float(_MAX_ANALYSIS_SECONDS)),
    )


def _read_mono_prefix(path: Path) -> tuple[list[float], int]:
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            if sample_width != 2 or channels not in {1, 2} or sample_rate not in {44_100, 48_000}:
                raise ValueError("analysis requires mono/stereo PCM16 at 44.1 or 48 kHz")
            frame_count = min(audio.getnframes(), sample_rate * _MAX_ANALYSIS_SECONDS)
            raw = audio.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise ValueError("analysis source is not a valid PCM WAV") from exc
    if not raw:
        raise ValueError("analysis source is empty")
    if channels == 1:
        return [value[0] / 32768.0 for value in struct.iter_unpack("<h", raw)], sample_rate
    return [(left + right) / 65536.0 for left, right in struct.iter_unpack("<hh", raw)], sample_rate


def _estimate_bpm(samples: list[float], sample_rate: int) -> tuple[float | None, float]:
    block_size = max(1, sample_rate // _ENVELOPE_HZ)
    envelope = [
        sum(abs(value) for value in samples[offset : offset + block_size]) / block_size
        for offset in range(0, len(samples) - block_size + 1, block_size)
    ]
    if len(envelope) < _ENVELOPE_HZ * 4:
        return None, 0.0
    onset = [max(0.0, right - left) for left, right in pairwise(envelope)]
    onset_mean = sum(onset) / len(onset)
    centered = [value - onset_mean for value in onset]
    energy = sum(value * value for value in centered)
    if energy < 1e-8:
        return None, 0.0

    scores: list[tuple[float, int]] = []
    for bpm in range(60, 181):
        lag = round(60 * _ENVELOPE_HZ / bpm)
        if lag >= len(centered):
            continue
        numerator = sum(
            centered[index] * centered[index - lag] for index in range(lag, len(centered))
        )
        left_energy = sum(value * value for value in centered[lag:])
        right_energy = sum(value * value for value in centered[:-lag])
        denominator = math.sqrt(left_energy * right_energy)
        scores.append((numerator / denominator if denominator else 0.0, bpm))
    if not scores:
        return None, 0.0
    scores.sort(reverse=True)
    best_score, best_bpm = scores[0]
    separated = [score for score, bpm in scores if abs(bpm - best_bpm) >= 4]
    runner_up = max(separated, default=0.0)
    confidence = max(0.0, min(1.0, best_score * 0.72 + (best_score - runner_up) * 1.4))
    if best_score < 0.12:
        return None, 0.0
    return float(best_bpm), round(confidence, 6)


def _estimate_key(
    samples: list[float], sample_rate: int
) -> tuple[
    Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] | None,
    Literal["major", "minor"] | None,
    float,
]:
    frame_size = max(1024, sample_rate // 20)
    histogram = [0.0] * 12
    voiced_frames = 0
    total_frames = 0
    for offset in range(0, len(samples) - frame_size + 1, frame_size):
        frame = samples[offset : offset + frame_size]
        total_frames += 1
        rms = math.sqrt(sum(value * value for value in frame) / len(frame))
        if rms < 0.008:
            continue
        crossings = sum(1 for left, right in pairwise(frame) if left <= 0 < right)
        frequency = crossings * sample_rate / len(frame)
        if not 55.0 <= frequency <= 1760.0:
            continue
        midi = 69 + 12 * math.log2(frequency / 440.0)
        pitch_class = round(midi) % 12
        histogram[pitch_class] += rms
        voiced_frames += 1
    if total_frames == 0 or voiced_frames < max(4, total_frames // 20) or sum(histogram) == 0:
        return None, None, 0.0

    candidates: list[tuple[float, int, str]] = []
    for tonic in range(12):
        for mode, profile in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
            score = _cosine_similarity(histogram, _rotate(profile, tonic))
            candidates.append((score, tonic, mode))
    candidates.sort(reverse=True)
    best_score, tonic, mode = candidates[0]
    runner_up = candidates[1][0]
    coverage = min(1.0, voiced_frames / max(1, total_frames * 0.35))
    confidence = max(0.0, min(1.0, coverage * (best_score * 0.45 + (best_score - runner_up) * 3)))
    if confidence < 0.15:
        return None, None, 0.0
    tonic_name = cast(
        Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"],
        _TONICS[tonic],
    )
    mode_name = cast(Literal["major", "minor"], mode)
    return tonic_name, mode_name, round(confidence, 6)


def _rotate(values: tuple[float, ...], tonic: int) -> tuple[float, ...]:
    return tuple(values[(pitch_class - tonic) % 12] for pitch_class in range(12))


def _cosine_similarity(left: list[float], right: tuple[float, ...]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum(value * value for value in left) * sum(value * value for value in right)
    )
    return numerator / denominator if denominator else 0.0
