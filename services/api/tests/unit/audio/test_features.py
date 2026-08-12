from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from uuid import uuid4

from motif_forge.audio.features import extract_waveform_peaks, write_feature_for_profile
from motif_forge.domain.media_jobs import FeatureProfile


def _write_tone(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48_000)
        frames = []
        for index in range(48_000):
            value = round(math.sin(2 * math.pi * 220 * index / 48_000) * 16_000)
            frames.append(struct.pack("<hh", value, value))
        audio.writeframes(b"".join(frames))


def test_waveform_peaks_are_compact_deterministic_and_bounded(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    _write_tone(source)

    peaks = extract_waveform_peaks(source)
    first = write_feature_for_profile(
        source,
        artifact_root=tmp_path,
        project_id=uuid4(),
        source_content_hash="a" * 64,
        profile=FeatureProfile.WAVEFORM_PEAKS_V1,
    )

    assert len(peaks.peaks) <= 4096
    assert peaks.source_frames == 48_000
    assert first.byte_size < 200_000
    assert (tmp_path / first.storage_key).is_file()
