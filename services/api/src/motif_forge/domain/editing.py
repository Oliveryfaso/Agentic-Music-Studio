"""Bounded AI edit proposals and deterministic, side-effect-free simulation."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import EditorCommand, Selection, apply_commands
from motif_forge.domain.errors import issue
from motif_forge.domain.ir import ArrangementIR, DomainModel
from motif_forge.domain.policies import compute_change_impact
from motif_forge.domain.revisions import ChangeImpact, StructuralDiffEntry

EDIT_PATCH_SCHEMA_VERSION = "edit-patch-proposal.v1"


class LockedRangeRef(DomainModel):
    track_id: UUID
    start_tick: int = Field(ge=0)
    end_tick: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_tick <= self.start_tick:
            raise ValueError("locked range end_tick must be greater than start_tick")
        return self


class EditVersionRefs(DomainModel):
    prompt: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="deterministic", min_length=1, max_length=80)
    policy: str = Field(default="change-impact.v1", min_length=1, max_length=80)
    graph: str = Field(default="motif-forge-parent.v2", min_length=1, max_length=80)


class EditPatchProposal(DomainModel):
    schema_version: Literal["edit-patch-proposal.v1"] = "edit-patch-proposal.v1"
    proposal_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    selection: Selection
    locked_ranges: tuple[LockedRangeRef, ...] = ()
    commands: tuple[EditorCommand, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=800)
    evidence_refs: tuple[str, ...] = ()
    expected_effect: str = Field(min_length=1, max_length=400)
    predicted_change_impact: ChangeImpact
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    versions: EditVersionRefs

    @model_validator(mode="after")
    def validate_commands(self) -> Self:
        if any(command.actor_kind != "agent" for command in self.commands):
            raise ValueError("edit proposals accept only agent commands")
        sequences = tuple(command.client_sequence for command in self.commands)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(sequences):
            raise ValueError("edit proposal commands require unique ordered client_sequence")
        return self


class AffectedRange(DomainModel):
    track_id: UUID
    start_tick: int = Field(ge=0)
    end_tick: int = Field(gt=0)


class EditSimulationResult(DomainModel):
    candidate_ir: ArrangementIR
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    structural_diff: tuple[StructuralDiffEntry, ...]
    affected_ranges: tuple[AffectedRange, ...]
    affected_track_ids: tuple[UUID, ...]
    non_target_preserved: Literal[True]
    non_target_preservation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_change_impact: ChangeImpact
    render_recommendation: Literal["none", "affected_range", "candidate_preview"]


def _command_track_id(command: EditorCommand) -> UUID | None:
    payload = command.payload
    track_id = getattr(payload, "track_id", None)
    return track_id if isinstance(track_id, UUID) else None


def _selection_range(selection: Selection, arrangement: ArrangementIR) -> tuple[int, int]:
    if selection.start_tick is None or selection.end_tick is None:
        return 0, max(1, arrangement.duration_tick)
    return selection.start_tick, selection.end_tick


def _assert_scope(arrangement: ArrangementIR, proposal: EditPatchProposal) -> None:
    selected = set(proposal.selection.track_ids)
    if not selected:
        raise issue("EDIT_SCOPE_INVALID", "selection.track_ids", "edit selection requires a track")
    start_tick, end_tick = _selection_range(proposal.selection, arrangement)
    for locked in proposal.locked_ranges:
        if (
            locked.track_id in selected
            and start_tick < locked.end_tick
            and locked.start_tick < end_tick
        ):
            raise issue(
                "LOCKED_RANGE_VIOLATION",
                f"locked_ranges.{locked.track_id}",
                "edit selection overlaps an authoritative locked range",
            )
    for command in proposal.commands:
        track_id = _command_track_id(command)
        if track_id is not None and track_id not in selected:
            raise issue(
                "EDIT_SCOPE_VIOLATION",
                f"commands.{command.command_id}",
                "command targets a track outside the declared selection",
            )
        command_selection = command.selection
        command_tracks = set(command_selection.track_ids)
        if command_tracks and not command_tracks.issubset(selected):
            raise issue(
                "EDIT_SCOPE_VIOLATION",
                f"commands.{command.command_id}.selection",
                "command selection exceeds the proposal selection",
            )
        if (
            command_selection.start_tick is not None
            and command_selection.end_tick is not None
            and (
                command_selection.start_tick < start_tick
                or command_selection.end_tick > end_tick
            )
        ):
            raise issue(
                "EDIT_SCOPE_VIOLATION",
                f"commands.{command.command_id}.selection",
                "command tick range exceeds the proposal selection",
            )


def _non_target_projection(arrangement: ArrangementIR, selection: Selection) -> ArrangementIR:
    selected = set(selection.track_ids)
    return arrangement.model_copy(
        update={
            "tracks": tuple(
                track for track in arrangement.tracks if track.track_id not in selected
            )
        }
    )


def _structural_diff(
    base: ArrangementIR, candidate: ArrangementIR, track_ids: tuple[UUID, ...]
) -> tuple[StructuralDiffEntry, ...]:
    before = {track.track_id: track for track in base.tracks}
    after = {track.track_id: track for track in candidate.tracks}
    entries: list[StructuralDiffEntry] = []
    for track_id in track_ids:
        if before.get(track_id) != after.get(track_id):
            entries.append(
                StructuralDiffEntry(
                    operation="replace",
                    path=f"tracks.{track_id}",
                    summary="selected track content or parameters changed",
                )
            )
    return tuple(entries)


def simulate_edit_patch(
    base: ArrangementIR, proposal: EditPatchProposal
) -> EditSimulationResult:
    """Apply an agent proposal in memory and prove it stayed inside its declared scope."""

    if base.project_id != proposal.project_id:
        raise issue("EDIT_PROJECT_MISMATCH", "project_id", "proposal targets another project")
    _assert_scope(base, proposal)
    non_target_before = _non_target_projection(base, proposal.selection)
    candidate = apply_commands(base, proposal.commands)
    non_target_after = _non_target_projection(candidate, proposal.selection)
    if non_target_before != non_target_after:
        raise issue(
            "EDIT_SCOPE_VIOLATION",
            "arrangement_ir",
            "candidate changed material outside the declared selection",
        )
    affected_track_ids = tuple(
        track_id
        for track_id in proposal.selection.track_ids
        if next((track for track in base.tracks if track.track_id == track_id), None)
        != next((track for track in candidate.tracks if track.track_id == track_id), None)
    )
    start_tick, end_tick = _selection_range(proposal.selection, base)
    affected_ranges = tuple(
        AffectedRange(track_id=track_id, start_tick=start_tick, end_tick=end_tick)
        for track_id in affected_track_ids
    )
    actual = max(proposal.predicted_change_impact, compute_change_impact(proposal.commands))
    recommendation: Literal["none", "affected_range", "candidate_preview"]
    if not affected_track_ids:
        recommendation = "none"
    elif actual >= ChangeImpact.L2:
        recommendation = "candidate_preview"
    else:
        recommendation = "affected_range"
    return EditSimulationResult(
        candidate_ir=candidate,
        candidate_content_hash=arrangement_content_hash(candidate),
        structural_diff=_structural_diff(base, candidate, affected_track_ids),
        affected_ranges=affected_ranges,
        affected_track_ids=affected_track_ids,
        non_target_preserved=True,
        non_target_preservation_hash=arrangement_content_hash(non_target_before),
        actual_change_impact=actual,
        render_recommendation=recommendation,
    )
