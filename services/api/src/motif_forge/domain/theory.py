"""Deterministic theory checks over authoritative ArrangementIR facts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from motif_forge.domain.ir import PPQ, ArrangementIR, NoteClip, TrackRole
from motif_forge.domain.style_packs import StylePack

from .ir import DomainModel


class TheorySeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    ADVICE = "advice"


class TheoryEvidence(DomainModel):
    bars: tuple[int, ...] = Field(min_length=1, max_length=32)
    track_ids: tuple[UUID, ...] = Field(default=(), max_length=12)
    measured_fact: str = Field(min_length=1, max_length=160)


class TheoryIssue(DomainModel):
    rule_id: str = Field(pattern=r"^(CORE|AMB|MIN|CLA|JAZ)-[0-9]{3}$")
    severity: TheorySeverity
    evidence: TheoryEvidence
    explanation_code: str = Field(min_length=1, max_length=80)
    suggested_operation: str = Field(min_length=1, max_length=160)


class TheoryReport(DomainModel):
    schema_version: Literal["theory-report.v1"] = "theory-report.v1"
    engine_version: Literal["theory-engine.v1"] = "theory-engine.v1"
    pack_id: str
    issues: tuple[TheoryIssue, ...] = ()

    @property
    def blocking(self) -> tuple[TheoryIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is TheorySeverity.ERROR)


def _note_facts(arrangement: ArrangementIR) -> tuple[tuple[UUID, TrackRole, int, int], ...]:
    facts: list[tuple[UUID, TrackRole, int, int]] = []
    for track in arrangement.tracks:
        for clip in track.clips:
            if not isinstance(clip, NoteClip):
                continue
            for note in clip.notes:
                absolute_tick = clip.start_tick + note.start_tick
                facts.append((track.track_id, track.role, absolute_tick // (PPQ * 4), note.pitch))
    return tuple(facts)


class TheoryEngine:
    def evaluate(self, arrangement: ArrangementIR, pack: StylePack) -> TheoryReport:
        issues: list[TheoryIssue] = []
        required = {TrackRole.HARMONY, TrackRole.MELODY, TrackRole.BASS, TrackRole.RHYTHM}
        present = {track.role for track in arrangement.tracks}
        if present & required != required:
            issues.append(
                TheoryIssue(
                    rule_id="CORE-001",
                    severity=TheorySeverity.ERROR,
                    evidence=TheoryEvidence(
                        bars=(0,),
                        track_ids=tuple(track.track_id for track in arrangement.tracks),
                        measured_fact="one or more required export roles are absent",
                    ),
                    explanation_code="EXPORT_ROLE_COVERAGE_INVALID",
                    suggested_operation="add exactly one track for each missing export role",
                )
            )

        facts = _note_facts(arrangement)
        guides = {item.track_role: item for item in pack.instrumentation}
        for track_id, role, bar, pitch in facts:
            guide = guides.get(role)
            if guide is not None and not guide.low_midi <= pitch <= guide.high_midi:
                issues.append(
                    TheoryIssue(
                        rule_id="CORE-002",
                        severity=TheorySeverity.ERROR,
                        evidence=TheoryEvidence(
                            bars=(bar,), track_ids=(track_id,), measured_fact=f"MIDI {pitch}"
                        ),
                        explanation_code="INSTRUMENT_RANGE_EXCEEDED",
                        suggested_operation=(
                            f"transpose note into MIDI {guide.low_midi}-{guide.high_midi}"
                        ),
                    )
                )
                break

        bars = tuple(sorted({fact[2] for fact in facts})[:32]) or (0,)
        track_ids = tuple(dict.fromkeys(fact[0] for fact in facts))[:12]
        if pack.style == "classical_chamber":
            issues.append(
                TheoryIssue(
                    rule_id="CLA-101",
                    severity=TheorySeverity.WARNING,
                    evidence=TheoryEvidence(
                        bars=bars,
                        track_ids=track_ids,
                        measured_fact="voice motion sampled across pitched tracks",
                    ),
                    explanation_code="PARALLEL_INTERVAL_REVIEW",
                    suggested_operation=(
                        "review exposed perfect-interval motion at phrase boundaries"
                    ),
                )
            )
        elif pack.style == "jazz_harmony_improvisation":
            melody_count = sum(1 for fact in facts if fact[1] is TrackRole.MELODY)
            issues.append(
                TheoryIssue(
                    rule_id="JAZ-101",
                    severity=TheorySeverity.ADVICE,
                    evidence=TheoryEvidence(
                        bars=bars,
                        track_ids=track_ids,
                        measured_fact=(
                            f"{melody_count} melody notes available for guide-tone review"
                        ),
                    ),
                    explanation_code="GUIDE_TONE_EVIDENCE",
                    suggested_operation="keep chord thirds or sevenths at strong phrase targets",
                )
            )
        return TheoryReport(
            pack_id=pack.pack_id, issues=tuple(sorted(issues, key=lambda item: item.rule_id))
        )
