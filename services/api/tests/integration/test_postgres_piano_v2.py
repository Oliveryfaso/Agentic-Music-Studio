"""Music v2 persistence, human preview approval, immutable reads and inverse history."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.previews import (
    CreateCommandPreview,
    CreateCommandPreviewRequest,
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.application.undo import UndoCommittedRevision, UndoCommittedRevisionRequest
from motif_forge.domain.canonical import arrangement_content_hash, canonical_json_bytes
from motif_forge.domain.commands import (
    Selection,
    SetPianoProfileCommand,
    SetPianoProfilePayload,
    SetTrackParamCommand,
    SetTrackParamPayload,
)
from motif_forge.domain.ir import (
    ArrangementIR,
    ArrangementIRV2,
    NoteClip,
    NoteEvent,
    NotePerformance,
    PerformancePlan,
    PianoRenderProfile,
    Section,
    Track,
    TrackType,
)
from motif_forge.domain.revisions import AuthorKind
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.project_reads import PostgresProjectReadStore


def _migrate(dsn: str, target="head", downgrade=False):
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        config = Config(Path(__file__).resolve().parents[4] / "alembic.ini")
        (command.downgrade if downgrade else command.upgrade)(config, target)


@pytest.mark.asyncio
async def test_piano_v2_approval_read_commands_and_exact_parent_undo(
    test_postgres_dsn: str,
    tmp_path: Path,
) -> None:
    await asyncio.to_thread(_migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    media = PostgresMediaJobUnitOfWork(sessions)
    try:
        project = await CreateProject(projects)(
            CreateProjectRequest(
                name="isolated v2 piano contract",
                actor_id="human-test",
                idempotency_key=uuid4().hex,
            )
        )
        track, clip, note = uuid4(), uuid4(), uuid4()
        score = ArrangementIR(
            project_id=project.project_id,
            sections=(
                Section(section_id=uuid4(), start_tick=0, end_tick=1920, label="self-authored"),
            ),
            tracks=(
                Track(
                    track_id=track,
                    track_type=TrackType.INSTRUMENT,
                    name="piano",
                    instrument_ref="builtin:jazz-piano",
                    clips=(
                        NoteClip(
                            clip_id=clip,
                            start_tick=0,
                            duration_tick=1920,
                            notes=(
                                NoteEvent(note_id=note, pitch=60, start_tick=0, duration_tick=240),
                            ),
                        ),
                    ),
                ),
            ),
        )
        async with projects() as tx:
            root = await tx.get_revision(project.root_revision_id)
            legacy = root.model_copy(
                update={
                    "revision_id": uuid4(),
                    "parent_revision_id": root.revision_id,
                    "command_batch_id": uuid4(),
                    "reason_code": "SELF_AUTHORED_PIANO_FIXTURE",
                    "arrangement_ir": score,
                    "content_hash": arrangement_content_hash(score),
                }
            )
            await tx.insert_revision(revision=legacy, commands=(), idempotency_key=uuid4().hex)
            assert await tx.advance_branch_head(
                branch_id=project.active_branch_id,
                expected_head_id=root.revision_id,
                new_head_id=legacy.revision_id,
            )
        performance = PerformancePlan(
            notes=(
                NotePerformance(
                    track_id=track,
                    clip_id=clip,
                    note_id=note,
                    velocity_override=72,
                    onset_offset_tick=8,
                ),
            )
        )

        async def approve_from(base):
            action = SetPianoProfileCommand(
                command_id=uuid4(),
                client_sequence=0,
                selection=Selection(track_ids=(track,)),
                payload=SetPianoProfilePayload(
                    render_profile=PianoRenderProfile(), performance_plan=performance
                ),
            )
            preview = await CreateCommandPreview(projects)(
                CreateCommandPreviewRequest(
                    project_id=project.project_id,
                    branch_id=project.active_branch_id,
                    base_revision_id=base,
                    candidate_id=uuid4(),
                    commands=(action,),
                    actor_id="human-test",
                    idempotency_key=uuid4().hex,
                )
            )
            async with projects() as tx:
                snapshot = await tx.get_candidate_snapshot(preview.candidate_snapshot_id)
                branch = await tx.lock_branch(
                    project_id=project.project_id, branch_id=project.active_branch_id
                )
            assert branch.head_revision_id == base and isinstance(
                snapshot.candidate_ir, ArrangementIRV2
            )
            assert snapshot.versions.audio_engine == "motif-forge-audio-engine.v2"
            decided = await DecidePreview(projects)(
                DecidePreviewRequest(
                    preview_id=preview.preview_id,
                    decision=PreviewDecision.APPROVE,
                    actor_id="human-test",
                    approval_assertion="I approve this exact self-authored piano interpretation.",
                    idempotency_key=uuid4().hex,
                )
            )
            async with projects() as tx:
                saved = await tx.get_revision(decided.revision_id)
            async with media() as tx:
                worker_read = await tx.get_revision(decided.revision_id)
            assert saved == worker_read and isinstance(saved.arrangement_ir, ArrangementIRV2)
            assert saved.arrangement_ir.performance_plan == performance
            studio = await PostgresProjectReadStore(sessions).read_revision_studio(
                project_id=project.project_id, revision_id=saved.revision_id
            )
            assert (
                studio.model_dump(mode="json")["arrangement_ir"]["render_profile"]["engine_version"]
                == "motif-forge-audio-engine.v2"
            )
            return saved

        saved = await approve_from(legacy.revision_id)
        from motif_forge.application.generation import EnqueueNextCompleteExportJob
        from motif_forge.application.media_jobs import EnqueueFollowupMediaJob, EnqueueMediaJob
        from motif_forge.application.revision_exports import (
            PrepareRevisionExport,
            RevisionExportRequest,
        )
        from motif_forge.infrastructure.persistence.export_reads import (
            PostgresExportProjectionStore,
        )

        cursor = await PrepareRevisionExport(media)(
            RevisionExportRequest(
                project_id=project.project_id,
                revision_id=saved.revision_id,
                request_id=uuid4(),
                include_mp3=False,
            ),
            thread_id="piano-contract-" + uuid4().hex,
        )
        queued = await EnqueueNextCompleteExportJob(
            media,
            enqueue_first=EnqueueMediaJob(media),
            enqueue_followup=EnqueueFollowupMediaJob(media),
        )(cursor)
        async with media() as tx:
            job = await tx.get_media_job(queued.pending_job_id)
        assert job.input_payload["schema_version"] == "canonical-render-job.v2"
        partial = await PostgresExportProjectionStore(
            sessions, artifact_root=tmp_path
        ).read_revision_export(
            project_id=project.project_id, revision_id=saved.revision_id, plan_hash=cursor.plan_hash
        )
        assert partial.export_plan.schema_version == "export-plan.v3" and partial.error_code is None
        assert tuple(step.step for step in partial.steps) == ("master", "bundle")
        # This is a metadata/file fixture, deliberately not a DSP or WAV-quality claim.
        import hashlib
        import json

        from motif_forge.application.exporting import write_export_bundle
        from motif_forge.domain.export_plan import plan_export
        from motif_forge.domain.exporting import AudioExportRef, ExportBundleRequestV2
        from motif_forge.domain.media_jobs import MediaQualityProfile

        source = tmp_path / "fixture.wav"
        source.write_bytes(b"self-authored-file-fixture")
        plan = plan_export(saved, seed=0, include_mp3=False, request_id=uuid4())
        bundle = write_export_bundle(
            artifact_root=tmp_path,
            request=ExportBundleRequestV2(
                plan=plan,
                plan_hash=plan.content_hash,
                arrangement=saved.arrangement_ir,
                audio_exports=(
                    AudioExportRef(
                        artifact_id=uuid4(),
                        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
                        storage_key="fixture.wav",
                        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                        byte_size=source.stat().st_size,
                        filename="master.wav",
                    ),
                ),
                trace_refs=("piano-contract-fixture",),
            ),
        )
        credits = json.loads((tmp_path / bundle.storage_prefix / "credits.json").read_text())
        license_manifest = json.loads(
            (tmp_path / bundle.storage_prefix / "license.json").read_text()
        )
        assert credits["credits"][0]["asset_id"] == "freepats:upright-kw-small"
        assert license_manifest["assets"][0]["spdx"] == "CC0-1.0"
        assert (
            license_manifest["assets"][0]["manifest_sha256"]
            == saved.arrangement_ir.render_profile.manifest_sha256
        )

        undone = await UndoCommittedRevision(projects)(
            UndoCommittedRevisionRequest(
                project_id=project.project_id,
                branch_id=project.active_branch_id,
                base_revision_id=saved.revision_id,
                target_revision_id=saved.revision_id,
                actor_id="human-test",
                idempotency_key=uuid4().hex,
            )
        )
        async with projects() as tx:
            restored = await tx.get_revision(undone.revision_id)
        assert restored.content_hash == legacy.content_hash and canonical_json_bytes(
            restored.arrangement_ir
        ) == canonical_json_bytes(score)
        saved = await approve_from(restored.revision_id)
        edited = await CommitCommandBatch(projects)(
            CommitCommandBatchRequest(
                project_id=project.project_id,
                branch_id=project.active_branch_id,
                base_revision_id=saved.revision_id,
                commands=(
                    SetTrackParamCommand(
                        command_id=uuid4(),
                        actor_kind="human",
                        client_sequence=0,
                        payload=SetTrackParamPayload(
                            track_id=track, parameter="gain_db", value=-3.0
                        ),
                    ),
                ),
                actor_id="human-test",
                author_kind=AuthorKind.HUMAN,
                reason="HUMAN_PIANO_GAIN",
                idempotency_key=uuid4().hex,
            )
        )
        async with projects() as tx:
            changed = await tx.get_revision(edited.revision_id)
        assert (
            isinstance(changed.arrangement_ir, ArrangementIRV2)
            and changed.arrangement_ir.performance_plan == performance
        )
        assert changed.versions.audio_engine == "motif-forge-audio-engine.v2"

        from motif_forge.domain.errors import DomainValidationError

        with pytest.raises(DomainValidationError, match="PIANO_INSTRUMENT_CHANGE_UNSUPPORTED"):
            await CommitCommandBatch(projects)(
                CommitCommandBatchRequest(
                    project_id=project.project_id,
                    branch_id=project.active_branch_id,
                    base_revision_id=edited.revision_id,
                    commands=(
                        SetTrackParamCommand(
                            command_id=uuid4(),
                            actor_kind="human",
                            client_sequence=0,
                            payload=SetTrackParamPayload(
                                track_id=track, parameter="instrument_ref", value="builtin:viola"
                            ),
                        ),
                    ),
                    actor_id="human-test",
                    author_kind=AuthorKind.HUMAN,
                    reason="UNSUPPORTED_PIANO_TIMBRE",
                    idempotency_key=uuid4().hex,
                )
            )
        async with projects() as tx:
            unchanged = await tx.lock_branch(
                project_id=project.project_id, branch_id=project.active_branch_id
            )
        assert unchanged.head_revision_id == edited.revision_id
        with pytest.raises(RuntimeError, match=r"(IR_V2|PIANO_EXPORT)_DOWNGRADE_BLOCKED"):
            await asyncio.to_thread(_migrate, test_postgres_dsn, "20261019_0023", True)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_piano_study_and_manual_workflow_replay_and_cancel(test_postgres_dsn: str):
    from motif_forge.application.errors import ApplicationError
    from motif_forge.application.piano_capability import PianoCapability
    from motif_forge.application.piano_preview import (
        PianoPreviewDecision,
        PianoPreviewRequest,
        PianoPreviewWorkflow,
    )
    from motif_forge.application.piano_study import CreatePianoStudy, PianoStudyRequest

    await asyncio.to_thread(_migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    media = PostgresMediaJobUnitOfWork(sessions)
    try:
        key = uuid4().hex
        study = await CreatePianoStudy(projects)(PianoStudyRequest(), idempotency_key=key)
        replay = await CreatePianoStudy(projects)(PianoStudyRequest(), idempotency_key=key)
        assert replay.replayed and replay.revision_id == study.revision_id

        async def capability():
            return PianoCapability(available=True)

        workflow = PianoPreviewWorkflow(projects, media, capability)
        request = PianoPreviewRequest(
            project_id=study.project_id,
            branch_id=study.branch_id,
            base_revision_id=study.revision_id,
            request_id=uuid4(),
        )
        prepared = await workflow.prepare(request, thread_id="piano-" + uuid4().hex)
        assert await workflow.prepare(request, thread_id=prepared.thread_id) == prepared
        baseline = await workflow.enqueue(prepared, step="baseline")
        replay_job = await workflow.enqueue(prepared, step="baseline")
        assert baseline.job_id == replay_job.job_id and replay_job.replayed
        async with media() as tx:
            job = await tx.get_media_job(baseline.job_id)
        assert job.input_payload["schema_version"] == "candidate-preview-job.v1"
        with pytest.raises(ApplicationError, match="Approval must bind"):
            await workflow.decide(
                prepared,
                PianoPreviewDecision(
                    action="approve",
                    expected_candidate_content_hash="f" * 64,
                    approval_assertion="Approve this exact candidate.",
                ),
                baseline,
            )
        await workflow.cancel(prepared, baseline)
        async with projects() as tx:
            branch = await tx.lock_branch(project_id=study.project_id, branch_id=study.branch_id)
            preview = await tx.lock_preview(prepared.preview_id)
        assert branch.head_revision_id == study.revision_id and preview.status.value == "rejected"
        # Metadata fixture proves the approval/read transaction.
        # The actual boundary probe covers DSP.
        from motif_forge.application.media_jobs import ApplyWorkerEvent
        from motif_forge.domain.media_jobs import (
            ArtifactLifecycle,
            AudioArtifact,
            MediaQualityProfile,
            RenderScope,
            WorkerEvent,
        )

        request = request.model_copy(update={"request_id": uuid4()})
        prepared = await workflow.prepare(request, thread_id="piano-" + uuid4().hex)
        for step in ("baseline", "piano"):
            cursor = await workflow.enqueue(prepared, step=step)
            artifact = AudioArtifact(
                artifact_id=uuid4(),
                project_id=study.project_id,
                candidate_snapshot_id=cursor.candidate_snapshot_id,
                arrangement_hash=cursor.candidate_content_hash,
                render_scope=RenderScope.MASTER,
                source_job_id=cursor.job_id,
                content_hash="d" * 64,
                byte_size=1000,
                storage_key="fixture/" + str(cursor.job_id) + ".mp3",
                media_role="candidate_preview",
                quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
                container="mp3",
                codec="mp3",
                sample_rate_hz=48000,
                channels=2,
                duration_seconds=30.0,
                bitrate_kbps=160,
                encoder="fixture",
                encoder_version="fixture.v1",
                lifecycle_class=ArtifactLifecycle.PROTECTED,
                created_at=datetime.now(UTC),
            )
            await ApplyWorkerEvent(media)(
                WorkerEvent(
                    event_id=uuid4().hex,
                    job_id=cursor.job_id,
                    event_type="job.completed",
                    artifact=artifact,
                    occurred_at=datetime.now(UTC),
                )
            )
            cursor = await workflow.collect(prepared, cursor, step=step)
        decided = await workflow.decide(
            prepared,
            PianoPreviewDecision(
                action="approve",
                expected_candidate_content_hash=prepared.candidate_content_hash,
                approval_assertion="Approve this exact rendered piano candidate.",
            ),
            cursor,
        )
        studio = await PostgresProjectReadStore(sessions).read_revision_studio(
            project_id=study.project_id, revision_id=decided.revision_id
        )
        assert (
            studio.delivery_assets
            and studio.delivery_assets[0].quality_profile == "candidate-preview.v1"
        )
        undone = await UndoCommittedRevision(projects)(
            UndoCommittedRevisionRequest(
                project_id=study.project_id,
                branch_id=study.branch_id,
                base_revision_id=decided.revision_id,
                target_revision_id=decided.revision_id,
                actor_id="human-test",
                idempotency_key=uuid4().hex,
            )
        )
        restored = await PostgresProjectReadStore(sessions).read_revision_studio(
            project_id=study.project_id, revision_id=undone.revision_id
        )
        assert (
            restored.delivery_assets
            and restored.delivery_assets[0].quality_profile == "candidate-preview.v1"
        )

    finally:
        await engine.dispose()
