from __future__ import annotations

import errno
import hashlib
import os
import subprocess
from pathlib import Path
from uuid import UUID

import pytest
from motif_forge.audio.transcode import ExportTranscodeError, transcode_master_to_mp3


def test_export_transcode_uses_bounded_ffmpeg_and_promotes_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_key = "protected/exports/project/revision/master-mix.wav"
    source = tmp_path / source_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-wav")
    (tmp_path / "explicit-temp").mkdir()
    real_replace = os.replace

    def reject_cross_device_replace(source: Path | str, target: Path | str) -> None:
        if Path(source).is_relative_to(tmp_path / "explicit-temp") and Path(target).is_relative_to(
            tmp_path / "protected"
        ):
            raise OSError(errno.EXDEV, "cross-device link")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", reject_cross_device_replace)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        del kwargs
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args,
                0,
                '{"streams":[{"sample_rate":"48000","channels":2,"bit_rate":"256000"}],'
                '"format":{"duration":"72.000000","bit_rate":"256000"}}',
                "",
            )
        if "volumedetect" in args:
            return subprocess.CompletedProcess(args, 0, b"", b"max_volume: -3.0 dB\n")
        assert args[args.index("-f") + 1] == "mp3"
        Path(args[-1]).write_bytes(b"ID3-delivery")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = transcode_master_to_mp3(
        artifact_root=tmp_path,
        temp_root=tmp_path / "explicit-temp",
        job_id=UUID("30000000-0000-4000-8000-000000000055"),
        project_id=UUID("10000000-0000-4000-8000-000000000055"),
        revision_id=UUID("20000000-0000-4000-8000-000000000055"),
        source_storage_key=source_key,
        expected_duration_seconds=72.0,
        timeout_seconds=60,
    )

    assert (tmp_path / result.storage_key).read_bytes() == b"ID3-delivery"
    assert result.sha256 == hashlib.sha256(b"ID3-delivery").hexdigest()
    assert result.sample_rate_hz == 48_000
    assert result.channels == 2
    assert result.duration_seconds == 72.0
    assert result.bitrate_kbps == 256
    assert result.created_new is True
    assert not (tmp_path / "tmp").exists()
    assert not (
        tmp_path
        / "explicit-temp"
        / "jobs"
        / "30000000-0000-4000-8000-000000000055"
    ).exists()


def test_export_transcode_rejects_invalid_probe_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_key = "protected/exports/project/revision/master-mix.wav"
    source = tmp_path / source_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-wav")
    (tmp_path / "explicit-temp").mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        del kwargs
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args,
                0,
                '{"streams":[{"sample_rate":"44100","channels":1,"bit_rate":"64000"}],'
                '"format":{"duration":"0.000000","bit_rate":"64000"}}',
                "",
            )
        if "volumedetect" in args:
            return subprocess.CompletedProcess(args, 0, b"", b"max_volume: -inf dB\n")
        Path(args[-1]).write_bytes(b"invalid-mp3")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ExportTranscodeError, match="TRANSCODE_MEDIA_PROFILE_INVALID"):
        transcode_master_to_mp3(
            artifact_root=tmp_path,
            temp_root=tmp_path / "explicit-temp",
            job_id=UUID("30000000-0000-4000-8000-000000000056"),
            project_id=UUID("10000000-0000-4000-8000-000000000056"),
            revision_id=UUID("20000000-0000-4000-8000-000000000056"),
            source_storage_key=source_key,
            expected_duration_seconds=72.0,
            timeout_seconds=60,
        )


def test_export_transcode_rejects_truncated_or_silent_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_key = "protected/exports/project/revision/master-mix.wav"
    source = tmp_path / source_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-wav")
    (tmp_path / "explicit-temp").mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        del kwargs
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args,
                0,
                '{"streams":[{"sample_rate":"48000","channels":2,"bit_rate":"256000"}],'
                '"format":{"duration":"12.000000","bit_rate":"256000"}}',
                "",
            )
        if "volumedetect" in args:
            return subprocess.CompletedProcess(args, 0, b"", b"max_volume: -inf dB\n")
        Path(args[-1]).write_bytes(b"truncated-silent-mp3")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ExportTranscodeError, match="TRANSCODE_DURATION_MISMATCH"):
        transcode_master_to_mp3(
            artifact_root=tmp_path,
            temp_root=tmp_path / "explicit-temp",
            job_id=UUID("30000000-0000-4000-8000-000000000057"),
            project_id=UUID("10000000-0000-4000-8000-000000000057"),
            revision_id=UUID("20000000-0000-4000-8000-000000000057"),
            source_storage_key=source_key,
            expected_duration_seconds=72.0,
            timeout_seconds=60,
        )


def test_export_transcode_rejects_near_silent_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_key = "protected/exports/project/revision/master-mix.wav"
    source = tmp_path / source_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-wav")
    (tmp_path / "explicit-temp").mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        del kwargs
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args,
                0,
                '{"streams":[{"sample_rate":"48000","channels":2,"bit_rate":"256000"}],'
                '"format":{"duration":"72.000000","bit_rate":"256000"}}',
                "",
            )
        if "volumedetect" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                b"",
                b"mean_volume: -96.0 dB\nmax_volume: -91.0 dB\n",
            )
        Path(args[-1]).write_bytes(b"near-silent-mp3")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ExportTranscodeError, match="TRANSCODE_SILENT_OUTPUT"):
        transcode_master_to_mp3(
            artifact_root=tmp_path,
            temp_root=tmp_path / "explicit-temp",
            job_id=UUID("30000000-0000-4000-8000-000000000058"),
            project_id=UUID("10000000-0000-4000-8000-000000000058"),
            revision_id=UUID("20000000-0000-4000-8000-000000000058"),
            source_storage_key=source_key,
            expected_duration_seconds=72.0,
            timeout_seconds=60,
        )


def test_export_transcode_accepts_quiet_but_intentional_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_key = "protected/exports/project/revision/master-mix.wav"
    source = tmp_path / source_key
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-wav")
    (tmp_path / "explicit-temp").mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        del kwargs
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args,
                0,
                '{"streams":[{"sample_rate":"48000","channels":2,"bit_rate":"256000"}],'
                '"format":{"duration":"72.000000","bit_rate":"256000"}}',
                "",
            )
        if "volumedetect" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                b"",
                b"mean_volume: -50.0 dB\nmax_volume: -42.0 dB\n",
            )
        Path(args[-1]).write_bytes(b"quiet-music-mp3")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = transcode_master_to_mp3(
        artifact_root=tmp_path,
        temp_root=tmp_path / "explicit-temp",
        job_id=UUID("30000000-0000-4000-8000-000000000059"),
        project_id=UUID("10000000-0000-4000-8000-000000000059"),
        revision_id=UUID("20000000-0000-4000-8000-000000000059"),
        source_storage_key=source_key,
        expected_duration_seconds=72.0,
        timeout_seconds=60,
    )

    assert result.sha256 == hashlib.sha256(b"quiet-music-mp3").hexdigest()
