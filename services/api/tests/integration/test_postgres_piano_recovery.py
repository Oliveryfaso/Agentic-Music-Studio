"""Real PostgreSQL discovery boundary; synthetic score/Graph fixtures, no renderer or model."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.piano_preview import PianoPreviewRequest, PianoPreviewWorkflow
from motif_forge.application.piano_recovery import ReadPianoRecovery
from motif_forge.application.piano_study import CreatePianoStudy, PianoStudyRequest
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.piano_recovery import PostgresPianoRecoveryStore
from motif_forge.infrastructure.persistence.project_reads import PostgresProjectReadStore
from motif_forge.infrastructure.persistence.tables import (
    BranchRow,
    PreviewCandidateRow,
    RevisionRow,
)
from sqlalchemy import select, text, update


def _migrate(dsn):
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(Path(__file__).resolve().parents[4] / "alembic.ini"), "head")


async def snapshot(sessions):
    async with sessions() as s:
        result = {}
        # The isolated test database contains only this test's fixtures, never user projects.
        for table in (
            "projects",
            "project_branches",
            "project_revisions",
            "preview_candidates",
            "candidate_snapshots",
            "idempotency_records",
            "runs",
            "jobs",
            "outbox_events",
            "ai_runs",
            "audit_events",
        ):
            result[table] = (
                await s.execute(
                    text(
                        f"SELECT coalesce(jsonb_agg(row ORDER BY row::text),'[]'::jsonb) "
                        f"FROM (SELECT to_jsonb(t) AS row FROM app.{table} t) q"
                    )
                )
            ).scalar_one()
        return result


@pytest.mark.asyncio
async def test_postgres_discovery_covers_baseline_dedup_scope_stale_expiry_and_no_writes(
    test_postgres_dsn,
):
    await asyncio.to_thread(_migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    media = PostgresMediaJobUnitOfWork(sessions)

    async def capability():
        return PianoCapability(available=True)

    workflow = PianoPreviewWorkflow(projects, media, capability)
    store = PostgresPianoRecoveryStore(sessions)
    now = datetime.now(UTC)
    try:
        study = await CreatePianoStudy(projects)(PianoStudyRequest(), idempotency_key=uuid4().hex)
        request = PianoPreviewRequest(
            project_id=study.project_id,
            branch_id=study.branch_id,
            base_revision_id=study.revision_id,
            request_id=uuid4(),
        )
        thread = "piano-" + uuid4().hex
        prepared = await workflow.prepare(request, thread_id=thread)
        params = dict(project_id=study.project_id, branch_id=study.branch_id, now=now, limit=11)
        # A crash before first enqueue is visible uncertainty, never a false empty directory.
        orphan = await store.list_sources(**params)
        assert len(orphan) == 1 and orphan[0].thread_id is None
        baseline = await workflow.enqueue(prepared, step="baseline")
        sources = await store.list_sources(**params)
        assert len(sources) == 1 and sources[0].thread_id == thread
        assert sources[0].preview_id == prepared.preview_id
        async with media() as tx:
            assert (await tx.get_media_job(baseline.job_id)).input_payload[
                "candidate_snapshot_id"
            ] == str(prepared.baseline_snapshot_id)
        # No piano Job existed for the preceding successful discovery.
        await workflow.enqueue(prepared, step="piano")
        assert await store.list_sources(**params) == sources

        other = await CreatePianoStudy(projects)(PianoStudyRequest(), idempotency_key=uuid4().hex)
        other_prepared = await workflow.prepare(
            PianoPreviewRequest(
                project_id=other.project_id,
                branch_id=other.branch_id,
                base_revision_id=other.revision_id,
                request_id=uuid4(),
            ),
            thread_id="piano-" + uuid4().hex,
        )
        await workflow.enqueue(other_prepared, step="baseline")
        assert await store.list_sources(**params) == sources
        assert not await store.list_sources(**(params | dict(branch_id=other.branch_id)))

        # A current-branch candidate remains discoverable after the head changes.
        # This synthetic fixture update is NOT a user-facing commit/undo or runtime E2E.
        async with sessions.begin() as s:
            parent = (
                await s.execute(
                    select(RevisionRow.parent_id).where(
                        RevisionRow.id == study.revision_id
                    )
                )
            ).scalar_one()
            assert parent is not None
            await s.execute(
                update(BranchRow)
                .where(BranchRow.id == study.branch_id)
                .values(head_revision_id=parent)
            )
        values = dict(
            operation="piano_preview",
            project_id=str(study.project_id),
            thread_id=thread,
            request_payload=request.model_dump(mode="json"),
            phase="waiting_piano_worker",
            piano_data=prepared.model_dump(mode="json"),
        )

        class ReadOnlyGraph:
            async def aget_state(self, config):
                assert config == {"configurable": {"thread_id": thread}}
                return SimpleNamespace(values=values, created_at=now.isoformat())

        read = ReadPianoRecovery(store, lambda: ReadOnlyGraph(), clock=lambda: now)
        before = await snapshot(sessions)
        first = await read(study.project_id, study.branch_id)
        assert first == await read(study.project_id, study.branch_id)
        assert first.recovery.status == "ready" and first.recovery.pending_count == 1
        assert first.recoverable.base_revision_id == study.revision_id
        workspace = await PostgresProjectReadStore(sessions).read_project(study.project_id)
        assert workspace.head_revision_id == parent
        assert await snapshot(sessions) == before
        assert len(before["ai_runs"]) == 0  # manual discovery never creates an AI Run

        # Expiry/status are fixtures; the directory itself never repairs or updates them.
        async with sessions.begin() as s:
            await s.execute(
                update(PreviewCandidateRow)
                .where(PreviewCandidateRow.id == prepared.preview_id)
                .values(expires_at=now - timedelta(seconds=1))
            )
        expired_before = await snapshot(sessions)
        assert not await store.list_sources(**params)
        assert await snapshot(sessions) == expired_before
        async with sessions.begin() as s:
            await s.execute(
                update(PreviewCandidateRow)
                .where(PreviewCandidateRow.id == prepared.preview_id)
                .values(expires_at=now + timedelta(days=1), status="rejected")
            )
        terminal_before = await snapshot(sessions)
        assert not await store.list_sources(**params)
        assert await snapshot(sessions) == terminal_before
    finally:
        await engine.dispose()
