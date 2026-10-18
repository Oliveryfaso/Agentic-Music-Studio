"""A2.1 filesystem boundary: self-authored PCM/real MP3, not piano or DB acceptance."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from uuid import UUID

from motif_forge.application.exporting import write_export_bundle
from motif_forge.application.generation import CompleteExportCursor, read_complete_export_cursor
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.exporting import (
    AudioExportRef,
    ExportBundleRequestV2,
    plan_export,
)
from motif_forge.domain.ir import ArrangementIR, NoteClip, NoteEvent, Section, Track, TrackType
from motif_forge.domain.revisions import Revision, create_root_state


def main(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    project_id = UUID(int=3101)
    score = ArrangementIR(
        project_id=project_id,
        sections=(
            Section(section_id=UUID(int=3102), start_tick=0, end_tick=1920, label="fixture"),
        ),
        tracks=(
            Track(
                track_id=UUID(int=3103),
                track_type=TrackType.INSTRUMENT,
                name="own fixture",
                instrument_ref="builtin:warm_pad",
                clips=(
                    NoteClip(
                        clip_id=UUID(int=3104),
                        start_tick=0,
                        duration_tick=1920,
                        notes=(
                            NoteEvent(
                                note_id=UUID(int=3105), pitch=60, start_tick=0, duration_tick=960
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    revision = create_root_state(project_id, created_by="test:a2").revision.model_copy(
        update={"arrangement_ir": score, "content_hash": arrangement_content_hash(score)}
    )
    revision = Revision.model_validate_json(revision.model_dump_json(), strict=True)
    audio = output / "protected/fixtures/a2"
    audio.mkdir(parents=True)
    pcm = bytearray()
    for frame in range(96000):
        seconds = frame / 48000
        amplitude = (
            0.2
            * math.sin(2 * math.pi * 261.625565 * seconds)
            * min(1, seconds / 0.01)
            * max(0, min(1, (1.05 - seconds) / 0.05))
        )
        sample = int(amplitude * ((1 << 23) - 1)).to_bytes(3, "little", signed=True)
        pcm.extend(sample * 2)
    with wave.open(str(audio / "master.wav"), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(3)
        target.setframerate(48000)
        target.writeframes(pcm)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(audio / "master.wav"),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "160k",
            "-map_metadata",
            "-1",
            str(audio / "master.mp3"),
        ],
        check=True,
    )
    stem_name = f"stem-{score.tracks[0].track_id}.wav"
    (audio / stem_name).write_bytes((audio / "master.wav").read_bytes())
    results = []
    for include_mp3, stems in [(False, ()), (True, ()), (True, (score.tracks[0].track_id,))]:
        plan = plan_export(revision, seed=7, include_mp3=include_mp3, stem_track_ids=stems)
        refs = []
        for index, (filename, profile) in enumerate(plan.audio_files):
            source = audio / filename
            refs.append(
                AudioExportRef(
                    artifact_id=UUID(int=3200 + index),
                    quality_profile=profile,
                    storage_key=source.relative_to(output).as_posix(),
                    sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    byte_size=source.stat().st_size,
                    filename=filename,
                )
            )
        request = ExportBundleRequestV2(
            plan=plan,
            plan_hash=plan.content_hash,
            arrangement=score,
            audio_exports=tuple(refs),
            trace_refs=("test:a2-filesystem",),
        )
        began = time.perf_counter()
        result = write_export_bundle(artifact_root=output, request=request)
        elapsed = time.perf_counter() - began
        bundle = output / result.storage_prefix
        manifest = json.loads((bundle / "export-manifest.json").read_text())
        for item in manifest["files"]:
            file = (
                (output / item["storage_key"])
                if "storage_key" in item
                else bundle / item["filename"]
            )
            assert file.stat().st_size == item["bytes"]
            assert hashlib.sha256(file.read_bytes()).hexdigest() == item["sha256"]
        again = write_export_bundle(artifact_root=output, request=request)
        assert not again.created_new and again.storage_prefix == result.storage_prefix
        cancelled = threading.Event()
        cancelled.set()
        try:
            write_export_bundle(artifact_root=output, request=request, cancel_event=cancelled)
        except ValueError as error:
            assert str(error) == "EXPORT_BUNDLE_CANCELLED"
        else:
            raise AssertionError("cancellation not preserved")
        assert (bundle / "export-manifest.json").is_file()
        assert not list(output.rglob("*.partial"))
        results.append(
            {
                "includeMp3": include_mp3,
                "requestedStems": [str(x) for x in stems],
                "planHash": plan.content_hash,
                "steps": plan.steps,
                "manifestFiles": result.file_count,
                "bundlePrefix": result.storage_prefix,
                "manifestHash": result.manifest_sha256,
                "allReferencedChecksumsVerified": True,
                "repeatReused": True,
                "cancelPreservedExisting": True,
                "latencySeconds": elapsed,
            }
        )
    legacy = CompleteExportCursor(
        project_id=project_id, revision_id=revision.revision_id, thread_id="test:legacy", seed=7
    )
    assert (
        read_complete_export_cursor(legacy.model_dump_json()).model_dump_json()
        == legacy.model_dump_json()
    )
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=codec_name,sample_rate,channels,bits_per_raw_sample",
                "-of",
                "json",
                str(audio / "master.wav"),
            ],
            text=True,
        )
    )
    report = {
        "schemaVersion": "a2-filesystem-boundary.v1",
        "scope": "internal-contract-and-filesystem-only",
        "fixture": "self-authored sine PCM + real FFmpeg MP3; not piano/canonical DSP proof",
        "providerRequests": 0,
        "providerTokens": 0,
        "databaseMeasured": False,
        "productionV2Activated": False,
        "realPianoAdmitted": False,
        "remainingPartials": 0,
        "legacyCursorByteRoundtrip": True,
        "ffprobe": probe,
        "runs": results,
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
