from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from motif_forge.audio.ingest import AudioIngestError, LocalAudioIngestor

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")


def _make_wav(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2:sample_rate=44100",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
    )


def test_ingest_validates_source_and_normalizes_to_working_pcm(tmp_path: Path) -> None:
    source = tmp_path / "quarantine/source.wav"
    source.parent.mkdir(parents=True)
    _make_wav(source)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()

    source_probe, result = LocalAudioIngestor(tmp_path).run(
        job_id=uuid4(),
        project_id=uuid4(),
        source_storage_key="quarantine/source.wav",
        source_hash=checksum,
        timeout_seconds=15,
    )

    assert source_probe.sample_rate_hz == 44_100
    assert source_probe.channels == 1
    assert result.probe.sample_rate_hz == 48_000
    assert result.probe.channels == 2
    assert result.probe.bit_depth == 16
    assert result.analysis.analysis_version == "import-analysis.v1"
    assert (tmp_path / result.storage_key).is_file()
    assert {item.feature_profile.value for item in result.feature_outputs} == {
        "waveform-peaks.v1",
        "imported-audio-analysis.v1",
    }
    assert all((tmp_path / item.storage_key).is_file() for item in result.feature_outputs)


def test_ingest_rejects_checksum_drift_before_decode(tmp_path: Path) -> None:
    source = tmp_path / "quarantine/source.wav"
    source.parent.mkdir(parents=True)
    _make_wav(source)

    with pytest.raises(AudioIngestError, match="SOURCE_ARTIFACT_CHECKSUM_MISMATCH"):
        LocalAudioIngestor(tmp_path).run(
            job_id=uuid4(),
            project_id=uuid4(),
            source_storage_key="quarantine/source.wav",
            source_hash="0" * 64,
            timeout_seconds=15,
        )
