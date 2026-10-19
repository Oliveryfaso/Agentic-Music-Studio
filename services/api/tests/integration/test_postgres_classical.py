"""P2 source/working branch identity and v3 exact-parent persistence on real PostgreSQL."""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from motif_forge.application.classical_import import ClassicalScoreRequest, CreateClassicalScore
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.previews import (
    CreateCommandPreview,
    CreateCommandPreviewRequest,
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.undo import UndoCommittedRevision, UndoCommittedRevisionRequest
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.project_reads import PostgresProjectReadStore


def migrate(dsn, target="head", down=False):
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        config = Config(Path(__file__).resolve().parents[4] / "alembic.ini")
        (command.downgrade if down else command.upgrade)(config, target)


@pytest.mark.asyncio
async def test_classical_import_replay_source_fork_v3_read_undo_and_downgrade_guard(
    test_postgres_dsn,
):
    await asyncio.to_thread(migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)

    async def available():
        return PianoCapability(available=True)

    try:
        key = "classical-pg:" + uuid4().hex
        imported = await CreateClassicalScore(projects, available)(
            ClassicalScoreRequest(), idempotency_key=key
        )
        replay = await CreateClassicalScore(projects, available)(
            ClassicalScoreRequest(), idempotency_key=key
        )
        assert (
            replay.replayed
            and replay.revision_id == imported.revision_id
            and replay.branch_id == imported.branch_id
        )
        async with projects() as tx:
            original = await tx.get_revision(imported.revision_id)
        action = accompaniment_command(
            original.arrangement_ir,
            AccompanimentIntent(pattern="broken", chords=("G",) * 16),
            request_id=uuid4(),
        )
        preview = await CreateCommandPreview(projects)(
            CreateCommandPreviewRequest(
                project_id=imported.project_id,
                branch_id=imported.branch_id,
                base_revision_id=imported.revision_id,
                candidate_id=uuid4(),
                commands=(action,),
                actor_id="human-test",
                idempotency_key=uuid4().hex,
            )
        )
        async with projects() as tx:
            branch = await tx.lock_branch(
                project_id=imported.project_id, branch_id=imported.branch_id
            )
        assert branch.head_revision_id == original.revision_id
        decided = await DecidePreview(projects)(
            DecidePreviewRequest(
                preview_id=preview.preview_id,
                decision=PreviewDecision.APPROVE,
                actor_id="human-test",
                approval_assertion="I approve this exact accompaniment preview.",
                idempotency_key=uuid4().hex,
            )
        )
        store = PostgresProjectReadStore(sessions)
        saved = await store.read_revision_studio(
            project_id=imported.project_id, revision_id=decided.revision_id
        )
        assert (
            saved.arrangement_ir.schema_version == "arrangement-ir.v3"
            and len(saved.arrangement_ir.tracks) == 2
        )
        assert original.arrangement_ir.tracks[0] in saved.arrangement_ir.tracks
        undone = await UndoCommittedRevision(projects)(
            UndoCommittedRevisionRequest(
                project_id=imported.project_id,
                branch_id=imported.branch_id,
                base_revision_id=decided.revision_id,
                target_revision_id=decided.revision_id,
                actor_id="human-test",
                idempotency_key=uuid4().hex,
            )
        )
        restored = await store.read_revision_studio(
            project_id=imported.project_id, revision_id=undone.revision_id
        )
        assert (
            restored.arrangement_ir == original.arrangement_ir
            and undone.content_hash == original.content_hash
        )
        async with projects() as tx:
            source = await tx.lock_branch(
                project_id=imported.project_id, branch_id=imported.source_branch_id
            )
        assert source.head_revision_id == original.revision_id
        with pytest.raises(RuntimeError, match="PIANO_ENSEMBLE_DOWNGRADE_BLOCKED"):
            await asyncio.to_thread(migrate, test_postgres_dsn, "20261019_0025", True)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_classical_failure_after_score_write_rolls_back_project_and_retry_is_exact(
    test_postgres_dsn,
):
    from motif_forge.infrastructure.persistence.database import PostgresTransaction
    from sqlalchemy import text

    await asyncio.to_thread(migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    key = "atomic-classical:" + uuid4().hex

    async def available():
        return PianoCapability(available=True)

    async def counts():
        async with engine.connect() as connection:
            return tuple(
                (
                    await connection.execute(
                        text(
                            """SELECT (SELECT count(*) FROM app.projects),
 (SELECT count(*) FROM app.project_revisions),
 (SELECT count(*) FROM app.project_branches),
 (SELECT count(*) FROM app.idempotency_records),
 (SELECT count(*) FROM app.audit_events)"""
                        )
                    )
                ).one()
            )

    try:
        before = await counts()
        with (
            patch.object(
                PostgresTransaction,
                "fork_active_branch",
                side_effect=RuntimeError("injected late import write failure"),
            ),
            pytest.raises(RuntimeError, match="injected late import"),
        ):
            await CreateClassicalScore(projects, available)(
                ClassicalScoreRequest(), idempotency_key=key
            )
        assert await counts() == before, "failed score import left a partial project"
        first = await CreateClassicalScore(projects, available)(
            ClassicalScoreRequest(), idempotency_key=key
        )
        replay = await CreateClassicalScore(projects, available)(
            ClassicalScoreRequest(), idempotency_key=key
        )
        assert (
            replay.replayed
            and replay.project_id == first.project_id
            and replay.branch_id == first.branch_id
            and replay.revision_id == first.revision_id
        )
        after = await counts()
        assert after[0] == before[0] + 1 and after[1] == before[1] + 2 and after[2] == before[2] + 2
    finally:
        await engine.dispose()
