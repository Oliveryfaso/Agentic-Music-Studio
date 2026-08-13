"""Versioned deterministic compatibility policy for the S2 Synth Ambient strategy."""

from __future__ import annotations

from collections import Counter

from pydantic import Field

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, KeyPlan
from motif_forge.domain.ir import DomainModel

SYNTH_AMBIENT_POLICY_VERSION = "synth-ambient-plan-policy.v1"

_REQUIRED_ROLES = ("pad", "melody", "bass", "rhythm")


class StrategyIssue(DomainModel):
    """One stable, machine-readable compatibility failure."""

    rule_id: str = Field(pattern=r"^SAP-[0-9]{3}$")
    code: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=240)


class StrategyValidation(DomainModel):
    """Ordered result of evaluating all Synth Ambient compatibility rules."""

    compatible: bool
    policy_version: str = SYNTH_AMBIENT_POLICY_VERSION
    issues: tuple[StrategyIssue, ...] = ()


def _issue(rule_id: str, code: str, path: str, message: str) -> StrategyIssue:
    return StrategyIssue(rule_id=rule_id, code=code, path=path, message=message)


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _target_key(value: str) -> KeyPlan | None:
    parts = value.replace("-", " ").split()
    if not parts:
        return None
    candidate = {"tonic": parts[0], "mode": parts[1].casefold() if len(parts) == 2 else "major"}
    try:
        return KeyPlan.model_validate(candidate, strict=True)
    except ValueError:
        return None


def validate_synth_ambient_plan(
    brief: CompositionBrief, plan: CompositionPlan
) -> StrategyValidation:
    """Evaluate authoritative schema facts in stable rule order and fail closed."""

    issues: list[StrategyIssue] = []

    if brief.style != "synth_ambient" or plan.genre != "synth_ambient":
        issues.append(
            _issue(
                "SAP-001",
                "STYLE_MISMATCH",
                "genre",
                "Synth Ambient requires both brief and plan to use synth_ambient",
            )
        )

    if brief.meter != "4/4" or plan.meter != "4/4":
        issues.append(
            _issue(
                "SAP-002",
                "METER_NOT_IMPLEMENTED",
                "meter",
                "the S2 Synth Ambient compiler supports only 4/4",
            )
        )

    beats_per_bar = 3 if plan.meter == "3/4" else 4
    bar_seconds = beats_per_bar * 60 / plan.bpm
    planned_seconds = plan.duration_bars * bar_seconds
    duration_tolerance = max(bar_seconds, brief.duration_seconds * 0.1)
    if abs(planned_seconds - brief.duration_seconds) > duration_tolerance:
        issues.append(
            _issue(
                "SAP-003",
                "DURATION_MISMATCH",
                "duration_bars",
                "planned duration exceeds the larger of one bar or ten percent tolerance",
            )
        )

    roles = Counter(_normalized_text(item.role) for item in plan.instrumentation)
    if roles != Counter(_REQUIRED_ROLES):
        issues.append(
            _issue(
                "SAP-004",
                "ROLE_COVERAGE_INVALID",
                "instrumentation",
                "exactly one pad, melody, bass, and rhythm role must map to built-in presets",
            )
        )

    plan_negative_constraints = {
        _normalized_text(item) for item in plan.negative_constraints
    }
    missing_negative_constraints = tuple(
        constraint
        for constraint in brief.negative_constraints
        if _normalized_text(constraint) not in plan_negative_constraints
    )
    if missing_negative_constraints:
        issues.append(
            _issue(
                "SAP-005",
                "NEGATIVE_CONSTRAINT_MISSING",
                "negative_constraints",
                "every brief negative constraint must be represented in the plan",
            )
        )

    if brief.target_bpm is not None and plan.bpm != brief.target_bpm:
        issues.append(
            _issue(
                "SAP-006",
                "BPM_MISMATCH",
                "bpm",
                "an explicit brief BPM must match the plan exactly",
            )
        )

    if brief.target_key is not None:
        requested_key = _target_key(brief.target_key)
        if requested_key is None or plan.key != requested_key:
            issues.append(
                _issue(
                    "SAP-007",
                    "KEY_MISMATCH",
                    "key",
                    "an explicit brief key and mode must match the plan exactly",
                )
            )

    if any(section.end_bar - section.start_bar > 32 for section in plan.sections):
        issues.append(
            _issue(
                "SAP-004",
                "SECTION_LENGTH_UNSUPPORTED",
                "sections",
                "each section must fit the PatternSpec v1 thirty-two-bar bound",
            )
        )

    return StrategyValidation(compatible=not issues, issues=tuple(issues))
