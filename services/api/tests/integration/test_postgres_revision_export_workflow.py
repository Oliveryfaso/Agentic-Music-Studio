"""Production API + PostgreSQL Parent checkpoints, cancellation and explicit retry."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.config import Settings
from motif_forge.domain.composition import build_s1_composition
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from sqlalchemy import text


def _upgrade(dsn: str) -> None:
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(Path(__file__).resolve().parents[4] / "alembic.ini"), "head")


@pytest.mark.asyncio
async def test_export_api_persists_scoped_attempts_replays_cancel_and_explicit_retry(
    test_postgres_dsn: str, tmp_path: Path
) -> None:
    await asyncio.to_thread(_upgrade, test_postgres_dsn)
    with patch("motif_forge.config.get_settings", return_value=Settings.for_test()):
        from motif_forge.api.app import create_app
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    project = await CreateProject(projects)(
        CreateProjectRequest(
            name="isolated export workflow", actor_id="test-human", idempotency_key=uuid4().hex
        )
    )
    arrangement = build_s1_composition(project.project_id, seed=7)
    async with projects() as transaction:
        root = await transaction.get_revision(project.root_revision_id)
        revision = root.model_copy(
            update={
                "revision_id": uuid4(),
                "parent_revision_id": root.revision_id,
                "command_batch_id": uuid4(),
                "reason_code": "SELF_AUTHORED_EXPORT_FIXTURE",
                "arrangement_ir": arrangement.arrangement,
                "content_hash": arrangement.content_hash,
            }
        )
        await transaction.insert_revision(
            revision=revision, commands=(), idempotency_key=uuid4().hex
        )
    settings = Settings.for_test(
        postgres_dsn=test_postgres_dsn,
        artifact_root=tmp_path / "artifacts",
        temp_root=tmp_path / "temp",
    )
    url = f"/api/v1/projects/{project.project_id}/revisions/{revision.revision_id}/exports"
    key = uuid4().hex
    try:
        app = create_app(settings)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            first = await client.post(
                url, json={"include_mp3": False}, headers={"Idempotency-Key": key}
            )
            assert first.status_code == 202, first.text
            a = first.json()["data"]
            replay = await client.post(
                url, json={"include_mp3": False}, headers={"Idempotency-Key": key}
            )
            assert replay.json()["data"]["pending_job_id"] == a["pending_job_id"]
            assert replay.json()["data"]["replayed"]
            conflict = await client.post(
                url, json={"include_mp3": True}, headers={"Idempotency-Key": key}
            )
            assert conflict.status_code == 409
            second = await client.post(
                url,
                json={"include_mp3": False, "include_all_stems": True},
                headers={"Idempotency-Key": uuid4().hex},
            )
            b = second.json()["data"]
            assert b["plan_hash"] != a["plan_hash"] and b["media_run_id"] != a["media_run_id"]
            for value, count in ((a, 2), (b, len(arrangement.arrangement.tracks) + 2)):
                projection = await client.get(url, params={"plan_hash": value["plan_hash"]})
                assert projection.status_code == 200, projection.text
                data = projection.json()["data"]
                assert data["plan_hash"] == value["plan_hash"] and len(data["steps"]) == count
                assert data["export_thread_id"] == value["thread_id"] and data["error_code"] is None
            thread = a["thread_id"]
        # A new app/checkpoint connection reads and cancels the original finite request.
        app = create_app(settings)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            status_url = url.replace("/exports", "/export-runs/") + thread
            assert (await client.get(status_url)).json()["data"]["phase"] == "waiting_export_worker"
            cancelled = await client.post(status_url + "/cancel")
            assert cancelled.status_code == 200 and cancelled.json()["data"]["phase"] == "cancelled"
            assert (await client.get(url, params={"plan_hash": a["plan_hash"]})).json()["data"][
                "status"
            ] == "cancelled"
            retried = await client.post(
                url, json={"include_mp3": False}, headers={"Idempotency-Key": uuid4().hex}
            )
            assert (
                retried.status_code == 202 and retried.json()["data"]["plan_hash"] != a["plan_hash"]
            )
        media = PostgresMediaJobUnitOfWork(sessions)
        async with media() as transaction:
            assert (
                await transaction.claim_media_job(
                    a["pending_job_id"],
                    worker_id="cancel-proof",
                    now=datetime.now(UTC),
                    lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
                )
                is None
            )
        async with engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        "SELECT count(*), count(DISTINCT run_id) FROM app.jobs WHERE project_id=:p"
                    ),
                    {"p": project.project_id},
                )
            ).one()
            assert tuple(counts) == (3, 3)
    finally:
        await engine.dispose()
