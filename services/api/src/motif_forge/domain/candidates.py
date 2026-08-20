"""Strict S5 candidate, evidence, and bounded segment contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from motif_forge.domain.ir import ArrangementIR, DomainModel, TrackRole


class CandidateLabel(StrEnum):
    A = "a"
    B = "b"


class CandidateSegment(DomainModel):
    schema_version: Literal["candidate-segment.v1"] = "candidate-segment.v1"
    segment_id: UUID
    candidate_id: UUID
    section_id: UUID
    section_name: str = Field(min_length=1, max_length=80)
    track_id: UUID
    track_role: TrackRole
    start_tick: int = Field(ge=0)
    end_tick: int = Field(gt=0)
    depends_on: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_tick <= self.start_tick:
            raise ValueError("candidate segment end must follow its start")
        if self.segment_id in self.depends_on:
            raise ValueError("candidate segment cannot depend on itself")
        return self


class CandidateEvidence(DomainModel):
    schema_version: Literal["candidate-evidence.v1"] = "candidate-evidence.v1"
    evidence_ref: str = Field(min_length=1, max_length=240)
    candidate_id: UUID
    segment_id: UUID | None = None
    kind: Literal["theory", "structure", "continuity", "audio", "repair"]
    severity: Literal["error", "warning", "advice", "info"]
    measured_fact: str = Field(min_length=1, max_length=500)
    score_delta: int = Field(default=0, ge=-100, le=100)


class CandidateFinding(DomainModel):
    finding_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,79}$")
    candidate_id: UUID
    segment_id: UUID | None = None
    severity: Literal["error", "warning", "advice"]
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=8)


class RepairProposal(DomainModel):
    candidate_id: UUID
    segment_id: UUID
    operation: Literal[
        "density_reduction",
        "velocity_rebalance",
        "register_shift",
        "onset_alignment",
    ]
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=8)


class CandidateAssessment(DomainModel):
    candidate_id: UUID
    label: CandidateLabel
    score: int = Field(ge=0, le=100)
    evidence_refs: tuple[str, ...] = Field(max_length=32)


class CandidateCritique(DomainModel):
    schema_version: Literal["candidate-critique.v1"] = "candidate-critique.v1"
    evidence: tuple[CandidateEvidence, ...]
    assessments: tuple[CandidateAssessment, ...] = Field(min_length=2, max_length=2)
    findings: tuple[CandidateFinding, ...] = Field(max_length=16)
    repair_proposal: RepairProposal | None = None
    recommended_candidate_id: UUID
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_evidence_and_pair(self) -> Self:
        labels = {item.label for item in self.assessments}
        if labels != {CandidateLabel.A, CandidateLabel.B}:
            raise ValueError("critique requires exactly candidate A and B")
        candidate_ids = {item.candidate_id for item in self.assessments}
        if len(candidate_ids) != 2 or self.recommended_candidate_id not in candidate_ids:
            raise ValueError("recommended candidate must belong to the assessed pair")
        known_refs = {item.evidence_ref for item in self.evidence}
        cited_refs = {
            ref
            for assessment in self.assessments
            for ref in assessment.evidence_refs
        } | {ref for finding in self.findings for ref in finding.evidence_refs}
        if self.repair_proposal is not None:
            cited_refs.update(self.repair_proposal.evidence_refs)
            if self.repair_proposal.candidate_id not in candidate_ids:
                raise ValueError("repair proposal candidate must belong to the assessed pair")
        if not cited_refs <= known_refs:
            raise ValueError("critique cites unknown evidence")
        if any(item.candidate_id not in candidate_ids for item in self.evidence):
            raise ValueError("evidence candidate must belong to the assessed pair")
        return self


class CandidateBranchResult(DomainModel):
    schema_version: Literal["candidate-branch-result.v1"] = "candidate-branch-result.v1"
    candidate_id: UUID
    label: CandidateLabel
    seed: int = Field(ge=0, le=2**31 - 1)
    candidate_snapshot_id: UUID
    latest_snapshot_id: UUID
    style_pack_version: str = Field(min_length=1, max_length=80)
    compiler_version: str = Field(min_length=1, max_length=80)
    preview_job_id: UUID | None = None
    preview_artifact_id: UUID | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    repair_status: Literal["not_requested", "improved", "non_improving"] = "not_requested"
    warnings: tuple[str, ...] = Field(default=(), max_length=16)


def derive_candidate_seed(base_seed: int, label: CandidateLabel) -> int:
    if not 0 <= base_seed <= 2**31 - 1:
        raise ValueError("candidate base seed is outside the supported range")
    if label is CandidateLabel.A:
        return base_seed
    return (base_seed + 1_048_583) % (2**31)


def _segment_id(candidate_id: UUID, section_id: UUID, track_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"motif-forge:s5-segment:{candidate_id}:{section_id}:{track_id}",
    )


def project_candidate_segments(
    candidate_id: UUID, arrangement: ArrangementIR
) -> tuple[CandidateSegment, ...]:
    raw: dict[tuple[UUID, UUID], CandidateSegment] = {}
    previous_by_track: dict[UUID, UUID] = {}
    role_order = {
        TrackRole.HARMONY: 0,
        TrackRole.RHYTHM: 1,
        TrackRole.BASS: 2,
        TrackRole.MELODY: 3,
        TrackRole.TEXTURE: 4,
        TrackRole.FX: 5,
        TrackRole.OTHER: 6,
    }
    for section in sorted(arrangement.sections, key=lambda item: item.start_tick):
        section_segments: dict[TrackRole, list[UUID]] = {}
        for track in sorted(
            arrangement.tracks,
            key=lambda item: (role_order[item.role], str(item.track_id)),
        ):
            segment_id = _segment_id(candidate_id, section.section_id, track.track_id)
            dependencies: list[UUID] = []
            previous = previous_by_track.get(track.track_id)
            if previous is not None:
                dependencies.append(previous)
            if track.role is TrackRole.RHYTHM:
                dependencies.extend(section_segments.get(TrackRole.HARMONY, ()))
            elif track.role is TrackRole.BASS:
                dependencies.extend(section_segments.get(TrackRole.RHYTHM, ()))
                dependencies.extend(section_segments.get(TrackRole.HARMONY, ()))
            elif track.role in {TrackRole.MELODY, TrackRole.TEXTURE, TrackRole.FX, TrackRole.OTHER}:
                dependencies.extend(section_segments.get(TrackRole.HARMONY, ()))
                dependencies.extend(section_segments.get(TrackRole.BASS, ()))
            segment = CandidateSegment(
                segment_id=segment_id,
                candidate_id=candidate_id,
                section_id=section.section_id,
                section_name=section.label,
                track_id=track.track_id,
                track_role=track.role,
                start_tick=section.start_tick,
                end_tick=section.end_tick,
                depends_on=tuple(dict.fromkeys(dependencies)),
            )
            raw[(section.section_id, track.track_id)] = segment
            section_segments.setdefault(track.role, []).append(segment_id)
            previous_by_track[track.track_id] = segment_id
    segments = tuple(
        sorted(
            raw.values(),
            key=lambda item: (
                item.start_tick,
                role_order[item.track_role],
                str(item.track_id),
            ),
        )
    )
    positions = {item.segment_id: index for index, item in enumerate(segments)}
    if any(
        dependency not in positions or positions[dependency] >= positions[item.segment_id]
        for item in segments
        for dependency in item.depends_on
    ):
        raise ValueError("candidate segment dependencies must be acyclic and ordered")
    return segments


def merge_candidate_branches(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in (*left, *right):
        candidate_id = str(item.get("candidate_id", ""))
        if not candidate_id:
            raise ValueError("candidate branch result requires candidate_id")
        existing = merged.get(candidate_id)
        if existing is not None and existing != item:
            raise ValueError("candidate branch identity returned divergent values")
        merged[candidate_id] = item
    if len(merged) > 2:
        raise ValueError("candidate fan-in cannot exceed two stable candidates")
    return [merged[key] for key in sorted(merged)]
