from uuid import uuid4

import pytest
from motif_forge.application.classical_import import (
    ClassicalScoreRequest,
    CreateClassicalScore,
    read_classical_source,
)
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.domain.ir import PianoRenderProfile

from .fakes import FakeTransaction


async def available():
    return PianoCapability(
        available=True,
        render_profile=PianoRenderProfile(),
        pedal_supported=False,
        release_triggers_supported=False,
    )


@pytest.mark.asyncio
async def test_import_keeps_original_branch_and_replay_does_not_duplicate_score():
    tx = FakeTransaction()
    service = CreateClassicalScore(tx, available)
    result = await service(ClassicalScoreRequest(), idempotency_key="source-import-test-1")
    assert len(tx.roots) == 1 and len(tx.revisions) == 2 and len(tx.branches) == 2
    assert tx.enter_count == 1 and tx.exit_errors == [None]
    assert tx.branches[result.source_branch_id].head_revision_id == result.revision_id
    assert tx.branches[result.branch_id].head_revision_id == result.revision_id
    assert result.branch_id != result.source_branch_id
    imported = tx.revisions[result.revision_id]
    assert imported.arrangement_ir.schema_version == "arrangement-ir.v2"
    assert imported.arrangement_ir.tracks[0].locked_ranges
    assert len(imported.arrangement_ir.tracks[0].clips[0].notes) == 62
    report = await read_classical_source(tx, result.project_id)
    assert (
        report["revision_id"] == str(result.revision_id)
        and report["source"]["license"] == "Public Domain"
    )
    assert (
        report["import_report"]["measure_count"] == 16
        and len(report["import_report"]["note_map"]) == 62
    )
    replay = await service(ClassicalScoreRequest(), idempotency_key="source-import-test-1")
    assert replay.replayed and replay.revision_id == result.revision_id
    assert len(tx.revisions) == 2 and len(tx.branches) == 2


@pytest.mark.asyncio
async def test_missing_reviewed_pack_prevents_creating_an_unplayable_classical_project():
    async def missing():
        return PianoCapability(available=False, error_code="INSTRUMENT_PACK_UNAVAILABLE")

    tx = FakeTransaction()
    with pytest.raises(ApplicationError, match="reviewed piano") as exc:
        await CreateClassicalScore(tx, missing)(
            ClassicalScoreRequest(), idempotency_key="missing-source-1"
        )
    assert exc.value.code == "INSTRUMENT_PACK_UNAVAILABLE" and not tx.roots


@pytest.mark.asyncio
async def test_classical_source_report_is_project_scoped():
    with pytest.raises(ApplicationError) as exc:
        await read_classical_source(FakeTransaction(), uuid4())
    assert exc.value.code == "CLASSICAL_SOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_manual_accompaniment_uses_existing_parent_preparation_and_preserves_source_branch():
    from motif_forge.application.piano_preview import PianoPreviewRequest, PianoPreviewWorkflow
    from motif_forge.domain.accompaniment import AccompanimentIntent

    tx = FakeTransaction()
    imported = await CreateClassicalScore(tx, available)(
        ClassicalScoreRequest(), idempotency_key="prepare-import-1"
    )

    def unused():
        raise AssertionError("prepare must not enqueue or spend")

    workflow = PianoPreviewWorkflow(tx, unused, available)
    prepared = await workflow.prepare(
        PianoPreviewRequest(
            project_id=imported.project_id,
            branch_id=imported.branch_id,
            base_revision_id=imported.revision_id,
            request_id=uuid4(),
            accompaniment=AccompanimentIntent(
                pattern="roots", chords=("G",) * 16, octave=2, velocity=54
            ),
        ),
        thread_id="piano-unit-accompaniment",
    )
    candidate = tx.candidate_snapshots[prepared.candidate_snapshot_id]
    original = tx.revisions[imported.revision_id]
    assert (
        candidate.candidate_ir.schema_version == "arrangement-ir.v3"
        and len(candidate.candidate_ir.tracks) == 2
    )
    assert original.arrangement_ir.tracks[0] in candidate.candidate_ir.tracks
    assert tx.branches[imported.source_branch_id].head_revision_id == imported.revision_id
    assert tx.branches[imported.branch_id].head_revision_id == imported.revision_id
