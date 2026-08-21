from __future__ import annotations

from uuid import UUID

import pytest
from motif_forge.application.candidate_repair import (
    ApplyBoundedCandidateRepair,
    BoundedRepairRequest,
    EvaluateCandidatePair,
)
from motif_forge.application.generation_candidates import (
    CreateCompositionCandidate,
    CreateCompositionCandidateRequest,
)
from motif_forge.domain.candidates import (
    CandidateEvidence,
    CandidateLabel,
    project_candidate_segments,
)
from motif_forge.domain.ir import NoteClip

from .test_generation_candidates import NOW, _fixture


def _notes_outside(snapshot, *, track_id: UUID, start_tick: int, end_tick: int):
    facts = []
    for track in snapshot.candidate_ir.tracks:
        for clip in track.clips:
            if not isinstance(clip, NoteClip):
                continue
            for note in clip.notes:
                absolute_tick = clip.start_tick + note.start_tick
                if track.track_id != track_id or not start_tick <= absolute_tick < end_tick:
                    facts.append((track.track_id, clip.clip_id, note))
    return tuple(facts)


@pytest.mark.asyncio
async def test_repair_changes_only_target_track_and_tick_range_and_replays() -> None:
    transaction, run, plan = await _fixture()
    created = await CreateCompositionCandidate(transaction, clock=lambda: NOW)(
        CreateCompositionCandidateRequest(
            run_id=run.run_id,
            project_id=run.project_id,
            branch_id=run.branch_id,
            base_revision_id=run.base_revision_id,
            plan_id=plan.plan_id,
            expected_plan_hash=plan.content_hash,
            label=CandidateLabel.A,
            seed=0,
        )
    )
    parent = transaction.candidate_snapshots[created.candidate_snapshot_id]
    segment = next(
        item
        for item in project_candidate_segments(parent.candidate_id, parent.candidate_ir)
        if any(
            isinstance(clip, NoteClip)
            and any(
                item.start_tick <= clip.start_tick + note.start_tick < item.end_tick
                for note in clip.notes
            )
            for track in parent.candidate_ir.tracks
            if track.track_id == item.track_id
            for clip in track.clips
        )
    )
    request = BoundedRepairRequest(
        run_id=run.run_id,
        project_id=run.project_id,
        parent_candidate_snapshot_id=parent.candidate_snapshot_id,
        segment=segment,
        operation="velocity_rebalance",
        evidence=(
            CandidateEvidence(
                evidence_ref="candidate:a:velocity",
                candidate_id=parent.candidate_id,
                segment_id=segment.segment_id,
                kind="repair",
                severity="warning",
                measured_fact="target segment velocities are imbalanced",
                score_delta=-4,
            ),
        ),
        evidence_refs=("candidate:a:velocity",),
    )
    repair = ApplyBoundedCandidateRepair(transaction, clock=lambda: NOW)

    first = await repair(request)
    replay = await repair(request)

    child = transaction.candidate_snapshots[first.child_snapshot_id]
    assert child.parent_candidate_snapshot_id == parent.candidate_snapshot_id
    assert child.candidate_content_hash != parent.candidate_content_hash
    assert _notes_outside(
        child,
        track_id=segment.track_id,
        start_tick=segment.start_tick,
        end_tick=segment.end_tick,
    ) == _notes_outside(
        parent,
        track_id=segment.track_id,
        start_tick=segment.start_tick,
        end_tick=segment.end_tick,
    )
    assert replay.child_snapshot_id == first.child_snapshot_id
    assert replay.replayed is True
    assert len(transaction.candidate_snapshots) == 2


def test_non_improving_repair_keeps_original_candidate() -> None:
    original = UUID("30000000-0000-0000-0000-000000000001")
    repaired = UUID("30000000-0000-0000-0000-000000000002")

    decision = EvaluateCandidatePair()(
        original_snapshot_id=original,
        repaired_snapshot_id=repaired,
        original_score=72,
        repaired_score=71,
        original_blocking_errors=0,
        repaired_blocking_errors=0,
    )

    assert decision.selected_snapshot_id == original
    assert decision.repair_status == "non_improving"


def test_repair_is_rejected_when_blocking_theory_errors_increase() -> None:
    original = UUID("30000000-0000-0000-0000-000000000001")
    repaired = UUID("30000000-0000-0000-0000-000000000002")

    decision = EvaluateCandidatePair()(
        original_snapshot_id=original,
        repaired_snapshot_id=repaired,
        original_score=72,
        repaired_score=80,
        original_blocking_errors=0,
        repaired_blocking_errors=1,
    )

    assert decision.selected_snapshot_id == original
    assert decision.repair_status == "non_improving"
