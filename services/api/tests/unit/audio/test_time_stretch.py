import hashlib
import math
import struct
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from motif_forge.audio.time_stretch import (
    LocalTimeStretchWorkspace,
    PitchPreservingTimeStretch,
    TimeStretchError,
    TimeStretchRequest,
)


def _write_stereo_sine(path: Path, *, seconds: float = 4.0, frequency: float = 440.0) -> None:
    sample_rate = 48000
    frame_count = round(sample_rate * seconds)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for frame in range(frame_count):
            envelope = min(1.0, frame / 240) * min(1.0, (frame_count - frame) / 240)
            sample = int(math.sin(2 * math.pi * frequency * frame / sample_rate) * envelope * 12000)
            frames.extend(struct.pack("<hh", sample, sample))
        output.writeframes(frames)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_time_stretch_changes_duration_and_preserves_pitch(tmp_path: Path) -> None:
    workspace = LocalTimeStretchWorkspace(tmp_path / "artifact-root")
    source_id = uuid4()
    source = workspace.source_slot(source_id)
    _write_stereo_sine(source)
    source_checksum = _sha256(source)
    operator = PitchPreservingTimeStretch(workspace)

    result = operator.run(
        TimeStretchRequest(
            job_id=uuid4(),
            source_artifact_id=source_id,
            source_bpm=120,
            target_bpm=96,
        )
    )

    assert _sha256(source) == source_checksum
    assert result.tempo_factor == pytest.approx(0.8)
    assert result.quality.actual_duration_seconds == pytest.approx(5.0, abs=0.05)
    assert result.quality.pitch_check == "passed"
    assert abs(result.quality.pitch_deviation_cents or 0) <= 25
    assert result.artifact.media_type == "audio/wav"
    assert result.artifact.artifact_id == f"sha256:{result.artifact.sha256}"


def test_time_stretch_is_content_reproducible_for_same_recipe(tmp_path: Path) -> None:
    workspace = LocalTimeStretchWorkspace(tmp_path / "artifact-root")
    source_id = uuid4()
    _write_stereo_sine(workspace.source_slot(source_id), seconds=2.0, frequency=220.0)
    operator = PitchPreservingTimeStretch(workspace)

    first = operator.run(
        TimeStretchRequest(
            job_id=uuid4(), source_artifact_id=source_id, source_bpm=100, target_bpm=125
        )
    )
    second = operator.run(
        TimeStretchRequest(
            job_id=uuid4(), source_artifact_id=source_id, source_bpm=100, target_bpm=125
        )
    )

    assert first.recipe_hash == second.recipe_hash
    assert first.artifact == second.artifact


def test_unsupported_ratio_fails_without_modifying_source(tmp_path: Path) -> None:
    workspace = LocalTimeStretchWorkspace(tmp_path / "artifact-root")
    source_id = uuid4()
    source = workspace.source_slot(source_id)
    _write_stereo_sine(source, seconds=1.0)
    source_checksum = _sha256(source)

    with pytest.raises(TimeStretchError) as raised:
        PitchPreservingTimeStretch(workspace).run(
            TimeStretchRequest(
                job_id=uuid4(), source_artifact_id=source_id, source_bpm=200, target_bpm=50
            )
        )

    assert raised.value.code == "TIME_STRETCH_RATIO_UNSUPPORTED"
    assert _sha256(source) == source_checksum
    assert list((tmp_path / "artifact-root" / "derived").rglob("*.wav")) == []


def test_workspace_rejects_symbolic_link_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ValueError, match="non-symlink"):
        LocalTimeStretchWorkspace(linked_root)


def test_workspace_resolves_only_repository_relative_persisted_storage_key(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifact-root"
    source_id = uuid4()
    source = root / "protected" / "normalized.wav"
    source.parent.mkdir(parents=True)
    _write_stereo_sine(source, seconds=1.0)
    workspace = LocalTimeStretchWorkspace(
        root, source_storage_keys={source_id: "protected/normalized.wav"}
    )

    result = PitchPreservingTimeStretch(workspace).run(
        TimeStretchRequest(
            job_id=uuid4(), source_artifact_id=source_id, source_bpm=120, target_bpm=120
        )
    )

    assert result.artifact.storage_key.startswith("derived/")
    assert (root / result.artifact.storage_key).is_file()
