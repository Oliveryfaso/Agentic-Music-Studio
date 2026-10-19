"""M2 real JSONB, reopened EQ/mix state, idempotency and exact v4 Undo."""

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
from motif_forge.domain.commands import (
    Selection,
    SetPianoEqCommand,
    SetPianoEqPayload,
    SetPianoMixCommand,
    SetPianoMixPayload,
)
from motif_forge.domain.ir import (
    ArrangementIRV5,
    PianoEqState,
    PianoMixState,
    PianoTrackEq,
    PianoTrackMix,
)
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
async def test_eq_jsonb_reopen_idempotent_batch_exact_undo_and_history_downgrade_guard(
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
        mixed = await CommitCommandBatch(projects)(
            CommitCommandBatchRequest(
                project_id=imported.project_id,
                branch_id=imported.branch_id,
                base_revision_id=base.revision_id,
                commands=(
                    SetPianoMixCommand(
                        command_id=uuid4(),
                        client_sequence=0,
                        selection=Selection(
                            track_ids=tuple(t.track_id for t in base.arrangement_ir.tracks)
                        ),
                        payload=SetPianoMixPayload(mix=initial),
                    ),
                ),
                actor_id="human:eq-test",
                author_kind=AuthorKind.HUMAN,
                reason="M2_MIX_BASE",
                idempotency_key=uuid4().hex,
            )
        )
        async with projects() as tx:
            base = await tx.get_revision(mixed.revision_id)
        flat = PianoEqState(
            tracks=tuple(PianoTrackEq(track_id=t.track_id) for t in base.arrangement_ir.tracks)
        )
        boosted = flat.model_copy(
            update={
                "tracks": (
                    flat.tracks[0].model_copy(update={"low_gain_db": 5.0, "mid_gain_db": -3.0}),
                    flat.tracks[1],
                )
            }
        )
        bypassed = boosted.model_copy(
            update={"tracks": tuple(t.model_copy(update={"bypass": True}) for t in boosted.tracks)}
        )
        commands = tuple(
            SetPianoEqCommand(
                command_id=uuid4(),
                client_sequence=index,
                selection=Selection(
                    track_ids=tuple(t.track_id for t in base.arrangement_ir.tracks)
                ),
                payload=SetPianoEqPayload(eq=eq),
            )
            for index, eq in enumerate((boosted, bypassed, flat))
        )
        request = CommitCommandBatchRequest(
            project_id=imported.project_id,
            branch_id=imported.branch_id,
            base_revision_id=base.revision_id,
            commands=commands,
            actor_id="human:mix-test",
            author_kind=AuthorKind.HUMAN,
            reason="M2_EQ_BATCH_FIXTURE",
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
        assert isinstance(reopened.arrangement_ir, ArrangementIRV5)
        assert reopened.arrangement_ir.tracks == base.arrangement_ir.tracks
        assert reopened.arrangement_ir.piano_mix == initial
        assert reopened.arrangement_ir.piano_eq == flat
        assert reopened.arrangement_ir.performance_plan == base.arrangement_ir.performance_plan
        async with projects() as tx:
            stored = await tx.get_revision(saved.revision_id)
            assert stored.versions.audio_engine == "motif-forge-audio-engine.v5"
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
        # Leaving v5 at the active head must not erase its immutable history.
        with pytest.raises(RuntimeError, match="PIANO_EQ_DOWNGRADE_BLOCKED"):
            await asyncio.to_thread(_migrate, test_postgres_dsn, "20261019_0028", True)
    finally:
        await engine.dispose()
