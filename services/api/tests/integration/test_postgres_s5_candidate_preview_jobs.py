"""PostgreSQL plus controlled render receipt and physical FFmpeg candidate boundary."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from motif_forge.application.candidate_previews import (
    CollectCandidatePreview,
    EnqueueCandidatePreview,
    EnqueueCandidatePreviewRequest,
)
from motif_forge.application.generation_candidates import (
    CreateCompositionCandidate,
    CreateCompositionCandidateRequest,
)
from motif_forge.application.media_jobs import (
    CancelMediaJob,
    CancelMediaJobRequest,
    StartArtifactRehydration,
    StartArtifactRehydrationRequest,
)
from motif_forge.audio.chromium_render import ChromiumRenderClient
from motif_forge.config import Settings
from motif_forge.domain.candidates import CandidateLabel
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    MediaQualityProfile,
    RenderScope,
)
from motif_forge.infrastructure.persistence.generation import (
    PostgresCompositionMaterializationUnitOfWork,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.worker.execution import execute_media_job
from sqlalchemy import text

from .test_postgres_generate_materialization import (
    _approved_materialization_fixture,
    _delete_exact_project,
)


@pytest.mark.asyncio
async def test_candidate_preview_real_mp3_and_duplicate_worker_delivery(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    temp_root = tmp_path / "temp"
    artifact_root.mkdir()
    temp_root.mkdir()
    engine, sessions, _, _, approved = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    materialization = PostgresCompositionMaterializationUnitOfWork(sessions)
    media = PostgresMediaJobUnitOfWork(sessions)
    storage_keys: list[str] = []
    try:
        candidate = await CreateCompositionCandidate(materialization)(
            CreateCompositionCandidateRequest(
                run_id=approved.run_id,
                project_id=approved.project_id,
                branch_id=approved.branch_id,
                base_revision_id=approved.base_revision_id,
                plan_id=approved.plan_id,
                expected_plan_hash=approved.expected_plan_hash,
                label=CandidateLabel.A,
                seed=0,
            )
        )
        enqueue = EnqueueCandidatePreview(media)
        request = EnqueueCandidatePreviewRequest(
            project_id=approved.project_id,
            candidate_snapshot_id=candidate.candidate_snapshot_id,
            expected_candidate_content_hash=candidate.candidate_content_hash,
            thread_id=f"candidate-preview:{approved.run_id}",
            seed=0,
            idempotency_key=f"candidate-preview:{candidate.candidate_snapshot_id}",
        )
        cursor = await enqueue(request)
        replayed_enqueue = await enqueue(request)
        assert replayed_enqueue.job_id == cursor.job_id
        assert replayed_enqueue.replayed is True

        # This test owns execution; prevent the already-running local dispatcher from racing it.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE app.outbox_events SET status='published', published_at=now() "
                    "WHERE aggregate_id=:job_id AND topic='media.job.dispatch.requested'"
                ),
                {"job_id": cursor.job_id},
            )
        settings = Settings(
            environment="test",
            postgres_dsn=test_postgres_dsn,
            artifact_root=artifact_root,
            temp_root=temp_root,
            render_service_url="http://render-worker.test",
            storage_min_free_bytes=64 * 1024**2,
        )

        async def render_receipt(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            duration = float(body["bridgeRequest"]["graph"]["durationSeconds"])
            frames = round(duration * 48_000)
            sample = struct.pack("<i", 180_000)[0:3] * 2
            audio = sample * frames
            wav = (
                b"RIFF"
                + struct.pack("<I", 36 + len(audio))
                + b"WAVEfmt "
                + struct.pack("<IHHIIHH", 16, 1, 2, 48_000, 48_000 * 6, 6, 24)
                + b"data"
                + struct.pack("<I", len(audio))
                + audio
            )
            checksum = hashlib.sha256(wav).hexdigest()
            output = temp_root / body["outputStorageKey"]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(wav)
            return httpx.Response(
                200,
                json={
                    "receiptVersion": "render-service-receipt.v1",
                    "requestId": body["requestId"],
                    "storageKey": body["outputStorageKey"],
                    "sha256": checksum,
                    "bytes": len(wav),
                    "durationSeconds": duration,
                    "sampleRate": 48_000,
                    "channels": 2,
                    "bitDepth": 24,
                    "peak": 0.021,
                },
            )

        render_client = ChromiumRenderClient(
            artifact_root=artifact_root,
            temp_root=temp_root,
            service_url="http://render-worker.test",
            transport=httpx.MockTransport(render_receipt),
        )
        with patch(
            "motif_forge.worker.execution.ChromiumRenderClient",
            return_value=render_client,
        ):
            first = await execute_media_job(
                cursor.job_id, settings=settings, worker_id="s5-candidate-preview-test"
            )
            replay = await execute_media_job(
                cursor.job_id, settings=settings, worker_id="s5-candidate-preview-replay"
            )
        assert (
            first.status,
            first.error_code,
            replay.status,
            replay.error_code,
        ) == ("succeeded", None, "succeeded", None)
        assert first.artifact_id == replay.artifact_id

        completed = await CollectCandidatePreview(media)(cursor, cursor.job_id)
        assert completed.preview_artifact_id == first.artifact_id
        async with media() as transaction:
            assert first.artifact_id is not None
            artifact = await transaction.get_audio_artifact(first.artifact_id)
        assert artifact is not None
        assert artifact.candidate_snapshot_id == candidate.candidate_snapshot_id
        assert artifact.revision_id is None
        assert artifact.source_job_id == cursor.job_id
        assert artifact.quality_profile is MediaQualityProfile.CANDIDATE_PREVIEW_V1
        assert artifact.render_scope is RenderScope.MASTER
        assert artifact.sample_rate_hz == 48_000
        assert artifact.channels == 2
        assert artifact.bitrate_kbps is not None and 152 <= artifact.bitrate_kbps <= 168
        storage_key = artifact.storage_key
        storage_keys.append(storage_key)
        output_path = (artifact_root / storage_key).resolve()
        assert output_path.is_relative_to(artifact_root.resolve())
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels,bit_rate:format=duration",
                "-of",
                "json",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        metadata = json.loads(probe.stdout)
        assert metadata["streams"][0]["sample_rate"] == "48000"
        assert metadata["streams"][0]["channels"] == 2
        assert abs(float(metadata["format"]["duration"]) - (artifact.duration_seconds or 0)) <= 0.05
        loudness = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                str(output_path),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert "max_volume: -inf" not in loudness.stderr
        candidate_b = await CreateCompositionCandidate(materialization)(
            CreateCompositionCandidateRequest(
                run_id=approved.run_id,
                project_id=approved.project_id,
                branch_id=approved.branch_id,
                base_revision_id=approved.base_revision_id,
                plan_id=approved.plan_id,
                expected_plan_hash=approved.expected_plan_hash,
                label=CandidateLabel.B,
                seed=1_048_583,
            )
        )
        cursor_b = await enqueue(
            request.model_copy(
                update={
                    "candidate_snapshot_id": candidate_b.candidate_snapshot_id,
                    "expected_candidate_content_hash": candidate_b.candidate_content_hash,
                    "seed": candidate_b.seed,
                    "idempotency_key": f"candidate-preview:{candidate_b.candidate_snapshot_id}",
                }
            )
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE app.outbox_events SET status='published', published_at=now() "
                    "WHERE aggregate_id=:job_id AND topic='media.job.dispatch.requested'"
                ),
                {"job_id": cursor_b.job_id},
            )
        with patch(
            "motif_forge.worker.execution.ChromiumRenderClient",
            return_value=render_client,
        ):
            second = await execute_media_job(
                cursor_b.job_id, settings=settings, worker_id="s5-candidate-preview-b"
            )
        assert second.status == "succeeded"
        completed_b = await CollectCandidatePreview(media)(cursor_b, cursor_b.job_id)
        assert completed_b.preview_artifact_id == second.artifact_id
        assert completed_b.preview_artifact_id != completed.preview_artifact_id
        assert second.artifact_id is not None
        async with media() as transaction:
            artifact_b = await transaction.get_audio_artifact(second.artifact_id)
        assert artifact_b is not None
        storage_keys.append(artifact_b.storage_key)

        # Eviction must be recoverable from the stored render recipe without
        # changing the authoritative Artifact identity or Snapshot lineage.
        output_path.unlink()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE app.artifacts SET availability='evicted', evicted_at=now() "
                    "WHERE id=:artifact_id"
                ),
                {"artifact_id": artifact.artifact_id},
            )
        rehydration = await StartArtifactRehydration(media)(
            StartArtifactRehydrationRequest(
                project_id=approved.project_id,
                artifact_id=artifact.artifact_id,
                thread_id=f"candidate-rehydrate:{artifact.artifact_id}",
                idempotency_key=f"candidate-rehydrate:{artifact.artifact_id}",
            )
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE app.outbox_events SET status='published', published_at=now() "
                    "WHERE aggregate_id=:job_id AND topic='media.job.dispatch.requested'"
                ),
                {"job_id": rehydration.job_id},
            )
        with patch(
            "motif_forge.worker.execution.ChromiumRenderClient",
            return_value=render_client,
        ):
            rebuilt = await execute_media_job(
                rehydration.job_id,
                settings=settings,
                worker_id="s5-candidate-preview-rehydrate",
            )
        assert rebuilt.status == "succeeded"
        assert rebuilt.artifact_id == artifact.artifact_id
        assert output_path.is_file()
        async with media() as transaction:
            recovered = await transaction.get_audio_artifact(artifact.artifact_id)
        assert recovered is not None
        assert recovered.availability is ArtifactAvailability.AVAILABLE
        assert recovered.candidate_snapshot_id == candidate.candidate_snapshot_id
        assert recovered.content_hash == artifact.content_hash
        assert recovered.recipe_hash == artifact.recipe_hash

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE app.artifacts SET availability='evicted', evicted_at=now() "
                    "WHERE id=:artifact_id"
                ),
                {"artifact_id": artifact.artifact_id},
            )
        cancelled_rehydration = await StartArtifactRehydration(media)(
            StartArtifactRehydrationRequest(
                project_id=approved.project_id,
                artifact_id=artifact.artifact_id,
                thread_id=f"candidate-rehydrate-cancel:{artifact.artifact_id}",
                idempotency_key=f"candidate-rehydrate-cancel:{artifact.artifact_id}",
            )
        )
        cancelled_job = await CancelMediaJob(media)(
            CancelMediaJobRequest(
                job_id=cancelled_rehydration.job_id,
                actor_id="s5-candidate-preview-test",
            )
        )
        assert cancelled_job.status.value == "cancelled"
        async with media() as transaction:
            released = await transaction.get_audio_artifact(artifact.artifact_id)
        assert released is not None
        assert released.availability is ArtifactAvailability.EVICTED
        assert released.rehydration_job_id is None

        async with engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM app.jobs WHERE project_id=:project_id), "
                        "(SELECT count(*) FROM app.artifacts "
                        " WHERE project_id=:project_id AND candidate_snapshot_id=:snapshot_id)"
                    ),
                    {
                        "project_id": approved.project_id,
                        "snapshot_id": candidate.candidate_snapshot_id,
                    },
                )
            ).one()
        assert tuple(counts) == (4, 1)
        async with engine.connect() as connection:
            all_candidate_artifacts = await connection.scalar(
                text(
                    "SELECT count(*) FROM app.artifacts WHERE project_id=:project_id "
                    "AND quality_profile='candidate-preview.v1'"
                ),
                {"project_id": approved.project_id},
            )
        assert all_candidate_artifacts == 2
    finally:
        for storage_key in storage_keys:
            output = (artifact_root / storage_key).resolve()
            root = artifact_root.resolve()
            if output.is_relative_to(root):
                output.unlink(missing_ok=True)
        async with engine.begin() as connection:
            await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            await connection.execute(
                text(
                    "DELETE FROM app.inbox_receipts WHERE event_id IN "
                    "(SELECT external_event_id FROM app.job_events WHERE job_id IN "
                    "(SELECT id FROM app.jobs WHERE project_id=:project_id))"
                ),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.artifacts WHERE project_id=:project_id"),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM app.outbox_events WHERE aggregate_id IN "
                    "(SELECT id FROM app.jobs WHERE project_id=:project_id)"
                ),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM app.job_events WHERE job_id IN "
                    "(SELECT id FROM app.jobs WHERE project_id=:project_id)"
                ),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM app.run_events WHERE run_id IN "
                    "(SELECT id FROM app.runs WHERE project_id=:project_id)"
                ),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.jobs WHERE project_id=:project_id"),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.runs WHERE project_id=:project_id"),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.storage_events WHERE project_id=:project_id"),
                {"project_id": approved.project_id},
            )
        await _delete_exact_project(engine, approved.project_id, approved.run_id)
        await engine.dispose()
