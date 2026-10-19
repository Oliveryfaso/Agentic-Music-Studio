"""M1 real JSONB, multi-command idempotency, reopened reads and exact-parent Undo."""

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
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.application.undo import UndoCommittedRevision, UndoCommittedRevisionRequest
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.commands import Selection, SetPianoMixCommand, SetPianoMixPayload
from motif_forge.domain.ir import ArrangementIRV4, PianoMixState, PianoTrackMix
from motif_forge.domain.revisions import AuthorKind
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.project_reads import PostgresProjectReadStore


def _migrate(dsn, target="head", downgrade=False):
    # Only the explicitly injected, disposable integration DSN is used.
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        config = Config(Path(__file__).resolve().parents[4] / "alembic.ini")
        (command.downgrade if downgrade else command.upgrade)(config, target)


@pytest.mark.asyncio
async def test_mix_jsonb_reopen_idempotent_batch_exact_undo_and_history_downgrade_guard(
    test_postgres_dsn,
):
    await asyncio.to_thread(_migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)

    async def available():
        return PianoCapability(available=True)

    try:
        imported = await CreateClassicalScore(projects, available)(
            ClassicalScoreRequest(), idempotency_key=uuid4().hex
        )
        async with projects() as tx:
            source = await tx.get_revision(imported.revision_id)
        action = accompaniment_command(
            source.arrangement_ir,
            AccompanimentIntent(pattern="broken", chords=("G",) * 16),
            request_id=uuid4(),
        )
        preview = await CreateCommandPreview(projects)(
            CreateCommandPreviewRequest(
                project_id=imported.project_id,
                branch_id=imported.branch_id,
                base_revision_id=source.revision_id,
                candidate_id=uuid4(),
                commands=(action,),
                actor_id="human:mix-test",
                idempotency_key=uuid4().hex,
            )
        )
        approved = await DecidePreview(projects)(
            DecidePreviewRequest(
                preview_id=preview.preview_id,
                decision=PreviewDecision.APPROVE,
                actor_id="human:mix-test",
                approval_assertion="I approve this exact piano fixture.",
                idempotency_key=uuid4().hex,
            )
        )
        async with projects() as tx:
            base = await tx.get_revision(approved.revision_id)
        initial = PianoMixState(
            tracks=tuple(
                PianoTrackMix(
                    track_id=t.track_id, gain_db=t.gain_db, pan=t.pan, mute=t.mute, solo=t.solo
                )
                for t in base.arrangement_ir.tracks
            )
        )
        quieter = initial.model_copy(
            update={
                "tracks": (
                    initial.tracks[0].model_copy(update={"gain_db": -8.0}),
                    initial.tracks[1],
                )
            }
        )
        panned = quieter.model_copy(
            update={
                "tracks": (
                    quieter.tracks[0].model_copy(update={"pan": -0.75}),
                    quieter.tracks[1].model_copy(update={"solo": True}),
                )
            }
        )
        commands = tuple(
            SetPianoMixCommand(
                command_id=uuid4(),
                client_sequence=index,
                selection=Selection(
                    track_ids=tuple(t.track_id for t in base.arrangement_ir.tracks)
                ),
                payload=SetPianoMixPayload(mix=mix),
            )
            for index, mix in enumerate((quieter, panned, initial))
        )
        request = CommitCommandBatchRequest(
            project_id=imported.project_id,
            branch_id=imported.branch_id,
            base_revision_id=base.revision_id,
            commands=commands,
            actor_id="human:mix-test",
            author_kind=AuthorKind.HUMAN,
            reason="M1_MIX_BATCH_FIXTURE",
            idempotency_key=uuid4().hex,
        )
        saved = await CommitCommandBatch(projects)(request)
        replay = await CommitCommandBatch(projects)(request)
        assert replay.replayed and replay.revision_id == saved.revision_id
        await engine.dispose()
        engine = create_postgres_engine(test_postgres_dsn)
        sessions = create_session_factory(engine)
        projects = PostgresUnitOfWork(sessions)
        store = PostgresProjectReadStore(sessions)
        reopened = await store.read_revision_studio(
            project_id=imported.project_id, revision_id=saved.revision_id
        )
        assert isinstance(reopened.arrangement_ir, ArrangementIRV4)
        assert reopened.arrangement_ir.tracks == base.arrangement_ir.tracks
        assert reopened.arrangement_ir.piano_mix == initial
        async with projects() as tx:
            stored = await tx.get_revision(saved.revision_id)
            assert stored.versions.audio_engine == "motif-forge-audio-engine.v4"
            assert stored.content_hash == saved.content_hash
        undone = await UndoCommittedRevision(projects)(
            UndoCommittedRevisionRequest(
                project_id=imported.project_id,
                branch_id=imported.branch_id,
                base_revision_id=saved.revision_id,
                target_revision_id=saved.revision_id,
                actor_id="human:mix-test",
                idempotency_key=uuid4().hex,
            )
        )
        restored = await store.read_revision_studio(
            project_id=imported.project_id, revision_id=undone.revision_id
        )
        assert restored.arrangement_ir == base.arrangement_ir
        assert undone.content_hash == base.content_hash
        # Leaving v4 at the active head must not erase its immutable history.
        with pytest.raises(RuntimeError, match="PIANO_MIX_DOWNGRADE_BLOCKED"):
            await asyncio.to_thread(_migrate, test_postgres_dsn, "20261019_0027", True)
    finally:
        await engine.dispose()
