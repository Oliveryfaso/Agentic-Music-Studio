from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from motif_forge.audio.analysis import analyze_imported_audio


def _write_click_track(path: Path, *, bpm: int = 120, seconds: int = 12) -> None:
    sample_rate = 48_000
    interval = round(sample_rate * 60 / bpm)
    frames: list[int] = []
    for index in range(sample_rate * seconds):
        click_offset = index % interval
        click = (
            0.75 * math.sin(2 * math.pi * 440 * index / sample_rate) if click_offset < 960 else 0
        )
        frames.append(round(click * 32767))
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"".join(struct.pack("<h", value) for value in frames))


def test_analysis_detects_pulsed_tempo_without_heavy_dependencies(tmp_path: Path) -> None:
    source = tmp_path / "click.wav"
    _write_click_track(source)

    analysis = analyze_imported_audio(source)

    assert analysis.bpm is not None
    assert abs(analysis.bpm - 120) <= 2
    assert analysis.bpm_confidence >= 0.5
    assert analysis.analysis_version == "import-analysis.v1"


def test_analysis_returns_unknown_for_silence(tmp_path: Path) -> None:
    source = tmp_path / "silence.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48_000)
        audio.writeframes(b"\x00\x00" * 48_000 * 5)

    analysis = analyze_imported_audio(source)

    assert analysis.bpm is None
    assert analysis.bpm_confidence == 0
    assert analysis.key_tonic is None
    assert analysis.key_confidence == 0


def test_analysis_detects_tonal_pulses_for_automatic_alignment(tmp_path: Path) -> None:
    source = tmp_path / "tonal-pulses.wav"
    sample_rate = 48_000
    bpm = 100
    interval = round(sample_rate * 60 / bpm)
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = []
        for index in range(sample_rate * 20):
            envelope = 1.0 if index % interval < round(sample_rate * 0.18) else 0.15
            value = 0.5 * envelope * math.sin(2 * math.pi * 261.6256 * index / sample_rate)
            frames.append(struct.pack("<h", round(value * 32767)))
        audio.writeframes(b"".join(frames))

    analysis = analyze_imported_audio(source)

    assert analysis.bpm == 100
    assert analysis.bpm_confidence >= 0.65
    assert analysis.key_tonic == "C"
    assert analysis.key_confidence >= 0.25
