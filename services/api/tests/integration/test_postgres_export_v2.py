"""Real PG -> bundle Worker -> files/read model; PCM is a file fixture, not a DSP claim."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.export_reads import ResolveBundleFile
from motif_forge.application.generation import (
    CollectCompleteExportArtifact,
    EnqueueNextCompleteExportJob,
)
from motif_forge.application.media_jobs import (
    ApplyWorkerEvent,
    EnqueueFollowupMediaJob,
    EnqueueMediaJob,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.config import Settings
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.export_plan import CompleteExportCursorV2, plan_export
from motif_forge.domain.ir import ArrangementIR, NoteClip, NoteEvent, Section, Track, TrackType
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    MediaQualityProfile,
    RenderScope,
    WorkerEvent,
)
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.export_reads import PostgresExportProjectionStore
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.worker.execution import execute_media_job
from sqlalchemy import text


def _upgrade(dsn: str) -> None:
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(Path(__file__).resolve().parents[4] / "alembic.ini"), "head")


@pytest.mark.asyncio
@pytest.mark.parametrize("one_stem", [False, True])
async def test_real_pg_v2_bundle_worker_preserves_plan_and_resume_identity(
    test_postgres_dsn: str,
    tmp_path: Path,
    one_stem: bool,
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects, media = PostgresUnitOfWork(sessions), PostgresMediaJobUnitOfWork(sessions)
    artifact_root, temp_root = tmp_path / "artifacts", tmp_path / "temp"
    artifact_root.mkdir()
    temp_root.mkdir()
    try:
        project = await CreateProject(projects)(
            CreateProjectRequest(
                name="A2.2 isolated export",
                actor_id="integration-human",
                idempotency_key="project-" + uuid4().hex,
            )
        )
        track_id = uuid4()
        arrangement = ArrangementIR(
            project_id=project.project_id,
            sections=(Section(section_id=uuid4(), start_tick=0, end_tick=1920, label="short"),),
            tracks=(
                Track(
                    track_id=track_id,
                    track_type=TrackType.INSTRUMENT,
                    name="One track",
                    instrument_ref="builtin:warm_pad",
                    clips=(
                        NoteClip(
                            clip_id=uuid4(),
                            start_tick=0,
                            duration_tick=1920,
                            notes=(
                                NoteEvent(
                                    note_id=uuid4(), pitch=60, start_tick=0, duration_tick=480
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        async with projects() as transaction:
            root = await transaction.get_revision(project.root_revision_id)
            assert root is not None
            revision = root.model_copy(
                update={
                    "revision_id": uuid4(),
                    "parent_revision_id": root.revision_id,
                    "command_batch_id": uuid4(),
                    "arrangement_ir": arrangement,
                    "content_hash": arrangement_content_hash(arrangement),
                    "reason_code": "SELF_AUTHORED_EXPORT_FIXTURE",
                }
            )
            await transaction.insert_revision(
                revision=revision, commands=(), idempotency_key="fixture-" + uuid4().hex
            )
            assert await transaction.advance_branch_head(
                branch_id=project.active_branch_id,
                expected_head_id=project.root_revision_id,
                new_head_id=revision.revision_id,
            )
        plan = plan_export(
            revision, seed=7, include_mp3=False, stem_track_ids=(track_id,) if one_stem else ()
        )
        cursor = CompleteExportCursorV2(
            plan=plan, plan_hash=plan.content_hash, thread_id="a22-" + uuid4().hex
        )
        enqueue = EnqueueNextCompleteExportJob(
            media,
            enqueue_first=EnqueueMediaJob(media),
            enqueue_followup=EnqueueFollowupMediaJob(media),
        )
        collect = CollectCompleteExportArtifact(media)
        while cursor.pending_steps[0] != "bundle":
            queued = await enqueue(cursor)
            assert (await enqueue(cursor)).pending_job_id == queued.pending_job_id
            partial_store = PostgresExportProjectionStore(sessions, artifact_root=artifact_root)
            partial = await partial_store.read_revision_export(
                project_id=project.project_id, revision_id=revision.revision_id
            )
            assert tuple(s.step for s in partial.steps) == (
                ("master", "stem:" + str(track_id), "bundle") if one_stem else ("master", "bundle")
            )
            assert partial.export_plan == plan
            now = datetime.now(UTC)
            async with media() as transaction:
                job = await transaction.claim_media_job(
                    queued.pending_job_id,
                    worker_id="self-authored-file-fixture",
                    now=now,
                    lease_expires_at=now + timedelta(minutes=1),
                )
            assert job is not None
            is_stem = cursor.pending_steps[0].startswith("stem:")
            key = "protected/fixture/" + str(job.job_id) + ".wav"
            path = artifact_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            pcm = b"".join(
                (
                    int(math.sin(i * 2 * math.pi * 440 / 48000) * 0.1 * 8388607).to_bytes(
                        3, "little", signed=True
                    )
                )
                * 2
                for i in range(12000)
            )
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(2)
                stream.setsampwidth(3)
                stream.setframerate(48000)
                stream.writeframes(pcm)
            blob = path.read_bytes()
            artifact = AudioArtifact(
                artifact_id=uuid4(),
                project_id=project.project_id,
                revision_id=revision.revision_id,
                arrangement_hash=revision.content_hash,
                render_scope=RenderScope.STEM if is_stem else RenderScope.MASTER,
                render_track_ids=(track_id,) if is_stem else (),
                source_job_id=job.job_id,
                content_hash=hashlib.sha256(blob).hexdigest(),
                byte_size=len(blob),
                storage_key=key,
                media_role="explicit_file_boundary_fixture",
                quality_profile=MediaQualityProfile.CANONICAL_STEM_V1
                if is_stem
                else MediaQualityProfile.CANONICAL_MASTER_V1,
                container="wav",
                codec="pcm",
                sample_rate_hz=48000,
                channels=2,
                duration_seconds=0.25,
                bit_depth=24,
                encoder="self-authored-file-fixture",
                encoder_version="1",
                lifecycle_class=ArtifactLifecycle.PROTECTED,
                created_at=now,
            )
            event = WorkerEvent(
                event_id="fixture-" + str(job.job_id),
                job_id=job.job_id,
                event_type="job.completed",
                artifact=artifact,
                occurred_at=now,
            )
            await ApplyWorkerEvent(media)(event)
            cursor = await collect(queued)
        queued = await enqueue(cursor)
        settings = Settings.for_test(
            postgres_dsn=test_postgres_dsn, artifact_root=artifact_root, temp_root=temp_root
        )
        result = await execute_media_job(
            queued.pending_job_id, settings=settings, worker_id="a22-real-bundle-worker"
        )
        assert result.status == "succeeded", result
        finished = await collect(queued)
        assert finished.pending_steps == ()
        assert (await collect(finished, completed_job_id=queued.pending_job_id)) == finished
        replay = await execute_media_job(
            queued.pending_job_id, settings=settings, worker_id="a22-duplicate-worker"
        )
        assert replay.artifact_id == result.artifact_id
        store = PostgresExportProjectionStore(sessions, artifact_root=artifact_root)
        projection = await store.read_revision_export(
            project_id=project.project_id, revision_id=revision.revision_id
        )
        assert projection is not None and projection.status == "ready"
        assert tuple(s.step for s in projection.steps) == (
            ("master", "stem:" + str(track_id), "bundle") if one_stem else ("master", "bundle")
        )
        assert len(projection.files) == (9 if one_stem else 8)
        download = await ResolveBundleFile(store, artifact_root=artifact_root)(
            result.artifact_id, "project.json"
        )
        assert hashlib.sha256(download.path.read_bytes()).hexdigest() == revision.content_hash
        async with engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        "SELECT (SELECT count(*) FROM app.jobs WHERE project_id=:p), "
                        "(SELECT count(*) FROM app.export_bundle_artifacts WHERE project_id=:p)"
                    ),
                    {"p": project.project_id},
                )
            ).one()
        assert tuple(counts) == ((3, 1) if one_stem else (2, 1))

        def downgrade_legacy_reader() -> None:
            with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": test_postgres_dsn}):
                command.downgrade(
                    Config(Path(__file__).resolve().parents[4] / "alembic.ini"), "20260824_0021"
                )

        with pytest.raises(
            RuntimeError,
            match=r"(EXPORT_(V2|REQUEST_IDENTITY)|IR_V2|PIANO_EXPORT)_DOWNGRADE_BLOCKED",
        ):
            await asyncio.to_thread(downgrade_legacy_reader)
        async with engine.connect() as connection:
            stored = (
                await connection.execute(
                    text(
                        "SELECT plan_hash, export_plan->>'schema_version' "
                        "FROM app.export_bundle_artifacts WHERE id=:id"
                    ),
                    {"id": result.artifact_id},
                )
            ).one()
        assert tuple(stored) == (plan.content_hash, "export-plan.v2")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_pg_legacy_bundle_write_and_reload_keeps_null_plan(
    test_postgres_dsn: str,
) -> None:
    from motif_forge.application.media_jobs import EnqueueMediaJobRequest
    from motif_forge.domain.media_jobs import ExportBundleArtifact, MediaJobType

    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    media = PostgresMediaJobUnitOfWork(sessions)
    try:
        project = await CreateProject(PostgresUnitOfWork(sessions))(
            CreateProjectRequest(
                name="A2.2 legacy receipt metadata fixture",
                actor_id="integration-human",
                idempotency_key="legacy-project-" + uuid4().hex,
            )
        )
        queued = await EnqueueMediaJob(media)(
            EnqueueMediaJobRequest(
                project_id=project.project_id,
                thread_id="legacy-" + uuid4().hex,
                run_type="complete_song_export.v1",
                job_type=MediaJobType.EXPORT_BUNDLE,
                input_payload={"revision_id": str(project.root_revision_id)},
                output_quality_profile=MediaQualityProfile.EXPORT_BUNDLE_V1,
                idempotency_key="legacy-bundle-" + uuid4().hex,
            )
        )
        now = datetime.now(UTC)
        receipt = ExportBundleArtifact(
            artifact_id=uuid4(),
            project_id=project.project_id,
            source_job_id=queued.job_id,
            revision_id=project.root_revision_id,
            content_hash="a" * 64,
            byte_size=1024,
            storage_prefix="protected/fixture/legacy",
            file_count=13,
            arrangement_hash="b" * 64,
            engine_version="motif-forge-audio-engine.v1",
            seed=7,
            input_artifact_ids=tuple(uuid4() for _ in range(6)),
            created_at=now,
        )
        await ApplyWorkerEvent(media)(
            WorkerEvent(
                event_id="legacy-" + uuid4().hex,
                job_id=queued.job_id,
                event_type="job.completed",
                artifact=receipt,
                occurred_at=now,
            )
        )
        async with media() as transaction:
            reloaded = await transaction.get_export_bundle_artifact(receipt.artifact_id)
        assert reloaded is not None and reloaded.schema_version == "export-bundle-artifact.v1"
        assert reloaded.model_dump_json() == receipt.model_dump_json()
        async with engine.connect() as connection:
            facts = (
                await connection.execute(
                    text(
                        "SELECT export_plan IS NULL, plan_hash IS NULL "
                        "FROM app.export_bundle_artifacts WHERE id=:id"
                    ),
                    {"id": receipt.artifact_id},
                )
            ).one()
        assert tuple(facts) == (True, True)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_pg_final_audio_keeps_job_identity_when_bytes_are_reused(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    from motif_forge.application.media_jobs import EnqueueMediaJobRequest
    from motif_forge.domain.media_jobs import MediaJobType

    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    media = PostgresMediaJobUnitOfWork(sessions)
    try:
        project = await CreateProject(PostgresUnitOfWork(sessions))(
            CreateProjectRequest(
                name="A2.2 final audio job identity fixture",
                actor_id="integration-human",
                idempotency_key="identity-project-" + uuid4().hex,
            )
        )
        async with media() as transaction:
            revision = await transaction.get_revision(project.root_revision_id)
        assert revision is not None
        with wave.open(str(tmp_path / "same.wav"), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(3)
            output.setframerate(48000)
            output.writeframes(bytes(1200 * 6))
        blob = (tmp_path / "same.wav").read_bytes()
        results = []
        for index in range(4):
            queued = await EnqueueMediaJob(media)(
                EnqueueMediaJobRequest(
                    project_id=project.project_id,
                    thread_id="identity-" + uuid4().hex,
                    run_type="explicit-final-export-fixture",
                    job_type=MediaJobType.RENDER_CANONICAL,
                    input_payload={"revision_id": str(revision.revision_id)},
                    output_quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
                    idempotency_key="same-final-bytes-" + uuid4().hex,
                )
            )
            now = datetime.now(UTC)
            artifact = AudioArtifact(
                artifact_id=uuid4(),
                project_id=project.project_id,
                revision_id=revision.revision_id,
                arrangement_hash=revision.content_hash,
                render_scope=RenderScope.MASTER,
                render_track_ids=(),
                source_job_id=queued.job_id,
                content_hash=hashlib.sha256(blob).hexdigest(),
                byte_size=len(blob),
                storage_key=(
                    "protected/fixture/same.wav"
                    if index < 2
                    else f"protected/fixture/{project.project_id}/different-{index}.wav"
                ),
                media_role="metadata_identity_fixture",
                quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
                container="wav",
                codec="pcm",
                sample_rate_hz=48000,
                channels=2,
                duration_seconds=0.025,
                bit_depth=24,
                encoder="self-authored-file-fixture",
                encoder_version="1",
                lifecycle_class=ArtifactLifecycle.PROTECTED,
                created_at=now,
            )
            result = await ApplyWorkerEvent(media)(
                WorkerEvent(
                    event_id="identity-" + uuid4().hex,
                    job_id=queued.job_id,
                    event_type="job.completed",
                    artifact=artifact,
                    occurred_at=now,
                )
            )
            async with media() as transaction:
                reloaded = await transaction.get_audio_artifact(result.artifact_id)
            assert reloaded.source_job_id == queued.job_id
            results.append(result.artifact_id)
        assert len(set(results)) == 4
        # Two records share one path; two equal-size objects on other paths still count.
        from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork

        async with PostgresStorageUnitOfWork(sessions)() as transaction:
            _, project_usage, _, _, _ = await transaction.load_storage_facts(
                project_id=project.project_id, dependency_artifact_ids=(), now=datetime.now(UTC)
            )
        assert project_usage == 3 * len(blob)
    finally:
        await engine.dispose()
