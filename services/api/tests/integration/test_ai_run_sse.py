from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from motif_forge.api.ai_runs import format_sse_event
from motif_forge.api.app import create_app
from motif_forge.application.ai_runs import (
    CreateAIRun,
    CreateAIRunRequest,
    ReadAIRun,
    RecordAIRunEvent,
    RecordCandidateCritique,
)
from motif_forge.application.candidate_previews import (
    CollectCandidatePreview,
    EnqueueCandidatePreview,
    EnqueueCandidatePreviewRequest,
)
from motif_forge.application.generation_candidates import (
    CreateCandidateSelectionPreview,
    CreateCandidateSelectionPreviewRequest,
    CreateCompositionCandidate,
    CreateCompositionCandidateRequest,
)
from motif_forge.application.media_jobs import ApplyWorkerEvent
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.config import Settings
from motif_forge.domain.ai_runs import AIRunEvent, AIRunStatus
from motif_forge.domain.candidates import (
    CandidateAssessment,
    CandidateCritique,
    CandidateLabel,
)
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    MediaQualityProfile,
    RenderScope,
    WorkerEvent,
)
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.generation import (
    PostgresCompositionMaterializationUnitOfWork,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from sqlalchemy import text

from .test_postgres_generate_materialization import (
    _approved_materialization_fixture,
    _delete_exact_project,
)


def test_sse_event_has_persistent_sequence_id_event_and_json_data() -> None:
    event = AIRunEvent(
        sequence=13, event_id=uuid4(), run_id=uuid4(), event_type="plan.persisted",
        phase="waiting_plan_approval", payload={"safe": True}, dedupe_key="plan",
    )
    encoded = format_sse_event(event)
    assert encoded.startswith("id: 13\nevent: plan.persisted\ndata: ")
    assert '"sequence":13' in encoded
    assert encoded.endswith("\n\n")


@pytest.mark.asyncio
async def test_persistent_sse_replays_after_last_id_across_app_recreation(
    test_postgres_dsn: str,
) -> None:
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    project = await CreateProject(PostgresUnitOfWork(sessions))(
        CreateProjectRequest(
            name=f"SSE {uuid4().hex}", actor_id="sse-test",
            idempotency_key=f"sse-project-{uuid4().hex}",
        )
    )
    uow = PostgresAIRunUnitOfWork(sessions)
    run = await CreateAIRun(uow)(CreateAIRunRequest.model_validate({
        "project_id": project.project_id, "branch_id": project.active_branch_id,
        "base_revision_id": project.root_revision_id, "thread_id": f"sse-{uuid4().hex}",
        "brief": {
            "title": "SSE", "purpose": "Persistent stream test",
            "style": "synth_ambient", "duration_seconds": 60, "moods": ("calm",),
        },
        "idempotency_key": f"sse-run-{uuid4().hex}",
    }))
    try:
        persisted: list[AIRunEvent] = []
        for sequence in range(2, 15):
            terminal = sequence == 14
            event_type = {
                12: "candidate.preview.ready",
                13: "candidate.critic.completed",
                14: "candidate.selection.completed",
            }.get(sequence, "run.progress")
            persisted.append(await RecordAIRunEvent(uow)(AIRunEvent(
                sequence=sequence, event_id=uuid4(), run_id=run.run_id,
                event_type=event_type,
                phase="succeeded" if terminal else "planning",
                payload={"sequence": sequence}, dedupe_key=f"sse-{sequence}",
            )))
        async with uow() as transaction:
            await transaction._session.execute(  # type: ignore[attr-defined]
                text(
                    "UPDATE app.ai_runs SET status=:status, version=version+1, "
                    "terminal_at=:terminal_at WHERE id=:run_id"
                ),
                {"status": AIRunStatus.SUCCEEDED.value, "terminal_at": datetime.now(UTC),
                 "run_id": run.run_id},
            )
        settings = Settings(postgres_dsn=test_postgres_dsn)
        replay_after = persisted[-3].sequence
        expected = (persisted[-2].sequence, persisted[-1].sequence)
        for _ in range(2):
            app = create_app(settings)
            transport = httpx.ASGITransport(app=app)
            async with (
                httpx.AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream(
                    "GET", f"/api/v1/runs/{run.run_id}/events",
                    headers={"Last-Event-ID": str(replay_after)},
                ) as response,
            ):
                body = await asyncio.wait_for(response.aread(), timeout=3)
            text_body = body.decode()
            first, second = (f"id: {value}\n" for value in expected)
            assert first in text_body and second in text_body
            assert f"id: {replay_after}\n" not in text_body
            assert text_body.index(first) < text_body.index(second)

            async with (
                httpx.AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream(
                    "GET", f"/api/v1/runs/{run.run_id}/events",
                    headers={"Last-Event-ID": str(expected[-1])},
                ) as response,
            ):
                terminal_reconnect = await asyncio.wait_for(response.aread(), timeout=1)
            assert terminal_reconnect == b""
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM app.audit_events WHERE project_id=:project_id"),
                {"project_id": project.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.projects WHERE id=:project_id"),
                {"project_id": project.project_id},
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_candidate_projection_and_selection_survive_app_recreation(
    test_postgres_dsn: str,
) -> None:
    engine, sessions, _, _, approved = await _approved_materialization_fixture(
        test_postgres_dsn
    )
    compositions = PostgresCompositionMaterializationUnitOfWork(sessions)
    media_uow = PostgresMediaJobUnitOfWork(sessions)
    ai_uow = PostgresAIRunUnitOfWork(sessions)
    candidates = []
    now = datetime.now(UTC)
    try:
        for label, seed in ((CandidateLabel.A, 0), (CandidateLabel.B, 1_048_583)):
            candidate = await CreateCompositionCandidate(compositions)(
                CreateCompositionCandidateRequest(
                    run_id=approved.run_id, project_id=approved.project_id,
                    branch_id=approved.branch_id,
                    base_revision_id=approved.base_revision_id, plan_id=approved.plan_id,
                    expected_plan_hash=approved.expected_plan_hash, label=label, seed=seed,
                )
            )
            cursor = await EnqueueCandidatePreview(media_uow)(
                EnqueueCandidatePreviewRequest(
                    project_id=approved.project_id,
                    candidate_snapshot_id=candidate.candidate_snapshot_id,
                    expected_candidate_content_hash=candidate.candidate_content_hash,
                    thread_id=f"candidate-api:{approved.run_id}", seed=seed,
                    idempotency_key=f"candidate-api:{candidate.candidate_snapshot_id}",
                )
            )
            artifact = AudioArtifact(
                artifact_id=uuid4(), project_id=approved.project_id,
                candidate_snapshot_id=candidate.candidate_snapshot_id,
                arrangement_hash=candidate.candidate_content_hash,
                render_scope=RenderScope.MASTER, source_job_id=cursor.job_id,
                content_hash=("a" if label is CandidateLabel.A else "b") * 64,
                byte_size=4096, storage_key=f"candidate/{label.value}.mp3",
                media_role="candidate_preview",
                quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
                container="mp3", codec="mp3", sample_rate_hz=48_000, channels=2,
                duration_seconds=30.0, bitrate_kbps=160, encoder="ffmpeg",
                encoder_version="7.1", lifecycle_class=ArtifactLifecycle.PROTECTED,
                created_at=now,
            )
            await ApplyWorkerEvent(media_uow)(WorkerEvent(
                event_id=f"candidate-api-worker-{label.value}", job_id=cursor.job_id,
                event_type="job.completed", artifact=artifact, occurred_at=now,
            ))
            completed = await CollectCandidatePreview(media_uow)(cursor, cursor.job_id)
            preview = await CreateCandidateSelectionPreview(compositions)(
                CreateCandidateSelectionPreviewRequest(
                    run_id=approved.run_id, project_id=approved.project_id,
                    branch_id=approved.branch_id,
                    base_revision_id=approved.base_revision_id,
                    candidate_snapshot_id=candidate.candidate_snapshot_id,
                    preview_artifact_id=completed.preview_artifact_id,
                    evidence_refs=(f"candidate:{candidate.candidate_id}:preview",),
                )
            )
            candidates.append((candidate, preview, artifact))
        critique = CandidateCritique(
            evidence=(),
            assessments=tuple(
                CandidateAssessment(
                    candidate_id=item[0].candidate_id, label=item[0].label,
                    score=70 + index, evidence_refs=(),
                )
                for index, item in enumerate(candidates)
            ),
            findings=(), repair_proposal=None,
            recommended_candidate_id=candidates[1][0].candidate_id,
            rationale="Candidate B has the stronger measured continuity.",
        )
        await RecordCandidateCritique(ai_uow)(approved.run_id, critique)

        settings = Settings(postgres_dsn=test_postgres_dsn)
        selected_candidate, selected_preview, _ = candidates[1]
        body = {
            "expected_version": (await ReadAIRun(ai_uow)(approved.run_id)).version,
            "preview_id": str(selected_preview.preview_id),
            "expected_candidate_id": str(selected_candidate.candidate_id),
            "expected_candidate_content_hash": selected_candidate.candidate_content_hash,
            "actor_id": "candidate-api-reviewer",
            "selection_assertion": "I compared both previews and select candidate B.",
            "decision": "select", "note": "authoritative API selection",
        }
        for attempt in range(2):
            app = create_app(settings)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                read = await client.get(f"/api/v1/runs/{approved.run_id}")
                assert read.status_code == 200
                data = read.json()["data"]
                assert data["pending_action"] == (
                    "select_candidate" if attempt == 0 else None
                )
                assert [item["label"] for item in data["candidates"]] == ["a", "b"]
                assert data["critique"]["recommended_candidate_id"] == str(
                    selected_candidate.candidate_id
                )
                selected = await client.post(
                    f"/api/v1/runs/{approved.run_id}/select-candidate",
                    headers={"Idempotency-Key": "candidate-api-select-key"}, json=body,
                )
                assert selected.status_code == 200
                if attempt == 0:
                    changed = await client.post(
                        f"/api/v1/runs/{approved.run_id}/select-candidate",
                        headers={"Idempotency-Key": "candidate-api-select-key"},
                        json={**body, "preview_id": str(candidates[0][1].preview_id)},
                    )
                    assert changed.status_code == 409
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM app.artifacts WHERE project_id=:project_id"),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM app.outbox_events WHERE aggregate_id IN "
                    "(SELECT id FROM app.jobs WHERE project_id=:project_id) OR "
                    "aggregate_id IN (SELECT id FROM app.runs WHERE project_id=:project_id)"
                ),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM app.inbox_receipts WHERE event_id IN "
                    "(SELECT event_id FROM app.job_events WHERE job_id IN "
                    "(SELECT id FROM app.jobs WHERE project_id=:project_id))"
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
                text("DELETE FROM app.jobs WHERE project_id=:project_id"),
                {"project_id": approved.project_id},
            )
            await connection.execute(
                text("DELETE FROM app.runs WHERE project_id=:project_id"),
                {"project_id": approved.project_id},
            )
        await _delete_exact_project(engine, approved.project_id, approved.run_id)
        await engine.dispose()
