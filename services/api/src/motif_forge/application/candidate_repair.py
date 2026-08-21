"""One deterministic, segment-bounded candidate repair and quality gate."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field, model_validator

from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import CompositionMaterializationUnitOfWorkFactory
from motif_forge.domain.ai_runs import AIRunEvent
from motif_forge.domain.candidates import (
    CandidateEvidence,
    CandidateSegment,
    project_candidate_segments,
)
from motif_forge.domain.commands import (
    DeleteNotesCommand,
    DeleteNotesPayload,
    EditorCommand,
    NoteUpdate,
    Selection,
    UpdateNotesCommand,
    UpdateNotesPayload,
    apply_commands,
)
from motif_forge.domain.ir import ArrangementIR, DomainModel, NoteClip
from motif_forge.domain.revisions import (
    StructuralDiffEntry,
    create_candidate_snapshot,
)

RepairOperation = Literal[
    "density_reduction",
    "velocity_rebalance",
    "register_shift",
    "onset_alignment",
]


class BoundedRepairRequest(DomainModel):
    schema_version: Literal["bounded-candidate-repair-request.v1"] = (
        "bounded-candidate-repair-request.v1"
    )
    run_id: UUID
    project_id: UUID
    parent_candidate_snapshot_id: UUID
    segment: CandidateSegment
    operation: RepairOperation
    evidence: tuple[CandidateEvidence, ...] = Field(min_length=1, max_length=16)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_evidence_refs(self) -> Self:
        supplied = {item.evidence_ref for item in self.evidence}
        if not set(self.evidence_refs) <= supplied:
            raise ValueError("repair cites evidence that was not supplied")
        if any(
            item.candidate_id != self.segment.candidate_id
            or item.segment_id != self.segment.segment_id
            for item in self.evidence
            if item.evidence_ref in self.evidence_refs
        ):
            raise ValueError("repair evidence must match the target candidate Segment")
        return self


class BoundedRepairResult(DomainModel):
    parent_snapshot_id: UUID
    child_snapshot_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: RepairOperation
    replayed: bool = False


class MeasuredCandidateEvidence(DomainModel):
    candidate_snapshot_id: UUID
    segment: CandidateSegment
    evidence: CandidateEvidence


class MeasureCandidateEvidence:
    """Project one reproducible density fact from an immutable Snapshot."""

    def __init__(self, uow_factory: CompositionMaterializationUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, candidate_snapshot_id: UUID) -> MeasuredCandidateEvidence:
        async with self._uow_factory() as transaction:
            snapshot = await transaction.get_candidate_snapshot(candidate_snapshot_id)
        if snapshot is None:
            raise ApplicationError(
                "CANDIDATE_NOT_FOUND", "candidate evidence target does not exist"
            )
        segments = project_candidate_segments(snapshot.candidate_id, snapshot.candidate_ir)

        def onset_count(segment: CandidateSegment) -> int:
            track = next(
                item
                for item in snapshot.candidate_ir.tracks
                if item.track_id == segment.track_id
            )
            return sum(
                1
                for clip in track.clips
                if isinstance(clip, NoteClip)
                for note in clip.notes
                if segment.start_tick
                <= clip.start_tick + note.start_tick
                < segment.end_tick
            )

        measured = tuple((segment, onset_count(segment)) for segment in segments)
        segment, count = max(measured, key=lambda item: (item[1], str(item[0].segment_id)))
        severity: Literal["warning", "info"] = "warning" if count > 4 else "info"
        delta = -min(20, (count - 4) * 2) if count > 4 else 0
        evidence = CandidateEvidence(
            evidence_ref=(
                f"candidate:{snapshot.candidate_id}:segment:{segment.segment_id}:density"
            ),
            candidate_id=snapshot.candidate_id,
            segment_id=segment.segment_id,
            kind="structure",
            severity=severity,
            measured_fact=f"note_onsets={count} in the measured Segment",
            score_delta=delta,
        )
        return MeasuredCandidateEvidence(
            candidate_snapshot_id=snapshot.candidate_snapshot_id,
            segment=segment,
            evidence=evidence,
        )


class QualityDecision(DomainModel):
    original_snapshot_id: UUID
    repaired_snapshot_id: UUID
    selected_snapshot_id: UUID
    repair_status: Literal["improved", "non_improving"]
    score_delta: int


class EvaluateCandidatePair:
    """Accept a repair only for strict score gain without added Theory errors."""

    def __init__(
        self,
        uow_factory: CompositionMaterializationUnitOfWorkFactory | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def __call__(
        self,
        *,
        original_snapshot_id: UUID,
        repaired_snapshot_id: UUID,
        original_score: int,
        repaired_score: int,
        original_blocking_errors: int,
        repaired_blocking_errors: int,
    ) -> QualityDecision:
        if not all(0 <= score <= 100 for score in (original_score, repaired_score)):
            raise ValueError("candidate quality scores must be between 0 and 100")
        if min(original_blocking_errors, repaired_blocking_errors) < 0:
            raise ValueError("blocking Theory error counts cannot be negative")
        improved = (
            repaired_score > original_score
            and repaired_blocking_errors <= original_blocking_errors
        )
        return QualityDecision(
            original_snapshot_id=original_snapshot_id,
            repaired_snapshot_id=repaired_snapshot_id,
            selected_snapshot_id=(
                repaired_snapshot_id if improved else original_snapshot_id
            ),
            repair_status="improved" if improved else "non_improving",
            score_delta=repaired_score - original_score,
        )

    async def record(self, *, run_id: UUID, decision: QualityDecision) -> AIRunEvent:
        if self._uow_factory is None:
            raise RuntimeError("quality decision recording requires a Unit of Work")
        event_type = f"candidate.repair.{decision.repair_status}"
        async with self._uow_factory() as transaction:
            return await transaction.record_ai_run_event(
                AIRunEvent(
                    sequence=1,
                    event_id=uuid4(),
                    run_id=run_id,
                    event_type=event_type,
                    phase="repairing_candidate",
                    payload={
                        "original_snapshot_id": str(decision.original_snapshot_id),
                        "repaired_snapshot_id": str(decision.repaired_snapshot_id),
                        "selected_snapshot_id": str(decision.selected_snapshot_id),
                        "score_delta": decision.score_delta,
                    },
                    dedupe_key=(
                        f"candidate-repair-quality:{decision.repaired_snapshot_id}"
                    ),
                    created_at=self._clock(),
                )
            )


class ApplyBoundedCandidateRepair:
    """Persist at most one stable child Snapshot for an allowlisted local edit."""

    def __init__(
        self,
        uow_factory: CompositionMaterializationUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def __call__(self, request: BoundedRepairRequest) -> BoundedRepairResult:
        child_id = uuid5(
            NAMESPACE_URL,
            "motif-forge:s5-repair:"
            f"{request.parent_candidate_snapshot_id}:{request.segment.segment_id}:"
            f"{request.operation}:v1",
        )
        async with self._uow_factory() as transaction:
            existing = await transaction.get_candidate_snapshot(child_id)
            if existing is not None:
                if (
                    existing.parent_candidate_snapshot_id
                    != request.parent_candidate_snapshot_id
                    or existing.project_id != request.project_id
                    or existing.source_run_id != request.run_id
                ):
                    raise ApplicationError(
                        "CANDIDATE_REPAIR_IDENTITY_CONFLICT",
                        "the stable Repair Snapshot contains different lineage",
                    )
                return BoundedRepairResult(
                    parent_snapshot_id=request.parent_candidate_snapshot_id,
                    child_snapshot_id=existing.candidate_snapshot_id,
                    candidate_content_hash=existing.candidate_content_hash,
                    operation=request.operation,
                    replayed=True,
                )
            parent = await transaction.get_candidate_snapshot(
                request.parent_candidate_snapshot_id
            )
            if (
                parent is None
                or parent.project_id != request.project_id
                or parent.source_run_id != request.run_id
                or parent.candidate_id != request.segment.candidate_id
            ):
                raise ApplicationError(
                    "CANDIDATE_REPAIR_LINEAGE_MISMATCH",
                    "the Repair target does not belong to the authoritative candidate",
                )
            base_revision = await transaction.get_revision(parent.base_revision_id)
            if base_revision is None:
                raise ApplicationError(
                    "REVISION_NOT_FOUND", "candidate base Revision does not exist"
                )
            commands = _compile_repair_commands(
                parent.candidate_ir,
                segment=request.segment,
                operation=request.operation,
                command_scope=child_id,
            )
            repaired = apply_commands(parent.candidate_ir, commands)
            _assert_non_target_unchanged(
                parent.candidate_ir,
                repaired,
                segment=request.segment,
            )
            child = create_candidate_snapshot(
                base_revision=base_revision,
                candidate_ir=repaired,
                candidate_id=parent.candidate_id,
                commands=commands,
                candidate_snapshot_id=child_id,
                source_run_id=request.run_id,
                parent_candidate_snapshot_id=parent.candidate_snapshot_id,
                structural_diff=(
                    StructuralDiffEntry(
                        operation="replace",
                        path=(
                            f"/tracks/{request.segment.track_id}/segments/"
                            f"{request.segment.start_tick}:{request.segment.end_tick}"
                        ),
                        summary=f"Bounded {request.operation} repair",
                    ),
                ),
                versions=parent.versions,
                created_at=self._clock(),
            )
            await transaction.insert_candidate_snapshot(child)
            await transaction.record_ai_run_event(
                event=_repair_event(request, child_id, self._clock())
            )
            return BoundedRepairResult(
                parent_snapshot_id=parent.candidate_snapshot_id,
                child_snapshot_id=child.candidate_snapshot_id,
                candidate_content_hash=child.candidate_content_hash,
                operation=request.operation,
            )


def _compile_repair_commands(
    arrangement: ArrangementIR,
    *,
    segment: CandidateSegment,
    operation: RepairOperation,
    command_scope: UUID,
) -> tuple[EditorCommand, ...]:
    track = next(
        (item for item in arrangement.tracks if item.track_id == segment.track_id),
        None,
    )
    if track is None:
        raise ApplicationError("CANDIDATE_REPAIR_TARGET_INVALID", "target track is missing")
    commands: list[EditorCommand] = []
    sequence = 0
    for clip in track.clips:
        if not isinstance(clip, NoteClip):
            continue
        targeted = tuple(
            note
            for note in clip.notes
            if segment.start_tick <= clip.start_tick + note.start_tick < segment.end_tick
        )
        if not targeted:
            continue
        selection = Selection(
            track_ids=(track.track_id,),
            start_tick=segment.start_tick,
            end_tick=segment.end_tick,
        )
        command_id = uuid5(NAMESPACE_URL, f"{command_scope}:{clip.clip_id}:{operation}")
        if operation == "density_reduction":
            removed = tuple(note.note_id for note in targeted[1::2])
            if not removed:
                continue
            commands.append(
                DeleteNotesCommand(
                    command_id=command_id,
                    selection=selection,
                    actor_kind="agent",
                    client_sequence=sequence,
                    payload=DeleteNotesPayload(
                        track_id=track.track_id,
                        clip_id=clip.clip_id,
                        note_ids=removed,
                    ),
                )
            )
        else:
            updates: list[NoteUpdate] = []
            for note in targeted:
                if operation == "velocity_rebalance":
                    velocity = note.velocity - 8 if note.velocity > 72 else note.velocity + 8
                    updates.append(
                        NoteUpdate(note_id=note.note_id, velocity=max(1, min(127, velocity)))
                    )
                elif operation == "register_shift":
                    pitch = note.pitch + 12 if note.pitch <= 115 else note.pitch - 12
                    updates.append(NoteUpdate(note_id=note.note_id, pitch=pitch))
                else:
                    grid = max(1, arrangement.ppq // 4)
                    absolute = clip.start_tick + note.start_tick
                    quantized = round(absolute / grid) * grid
                    quantized = min(max(quantized, segment.start_tick), segment.end_tick - 1)
                    local = quantized - clip.start_tick
                    if local != note.start_tick:
                        updates.append(NoteUpdate(note_id=note.note_id, start_tick=local))
            if not updates:
                continue
            commands.append(
                UpdateNotesCommand(
                    command_id=command_id,
                    selection=selection,
                    actor_kind="agent",
                    client_sequence=sequence,
                    payload=UpdateNotesPayload(
                        track_id=track.track_id,
                        clip_id=clip.clip_id,
                        updates=tuple(updates),
                    ),
                )
            )
        sequence += 1
    if not commands:
        raise ApplicationError(
            "CANDIDATE_REPAIR_NO_CHANGE",
            "the allowlisted Repair produced no change in the target Segment",
        )
    return tuple(commands)


def _assert_non_target_unchanged(
    before: ArrangementIR,
    after: ArrangementIR,
    *,
    segment: CandidateSegment,
) -> None:
    def outside(arrangement: ArrangementIR) -> tuple[object, ...]:
        facts: list[object] = []
        for track in arrangement.tracks:
            for clip in track.clips:
                if not isinstance(clip, NoteClip):
                    facts.append((track.track_id, clip))
                    continue
                for note in clip.notes:
                    absolute = clip.start_tick + note.start_tick
                    if (
                        track.track_id != segment.track_id
                        or not segment.start_tick <= absolute < segment.end_tick
                    ):
                        facts.append((track.track_id, clip.clip_id, note))
        return tuple(facts)

    if outside(before) != outside(after):
        raise ApplicationError(
            "CANDIDATE_REPAIR_SCOPE_VIOLATION",
            "the Repair changed material outside its target Segment",
        )


def _repair_event(
    request: BoundedRepairRequest, child_id: UUID, now: datetime
) -> AIRunEvent:
    return AIRunEvent(
        sequence=1,
        event_id=uuid4(),
        run_id=request.run_id,
        event_type="candidate.repair.applied",
        phase="repairing_candidate",
        payload={
            "parent_candidate_snapshot_id": str(request.parent_candidate_snapshot_id),
            "child_candidate_snapshot_id": str(child_id),
            "segment_id": str(request.segment.segment_id),
            "operation": request.operation,
            "evidence_refs": list(request.evidence_refs),
        },
        dedupe_key=f"candidate-repair:{child_id}",
        created_at=now,
    )
