"""Versioned deterministic routing for imported-audio analysis and alignment."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import ImportedAudioAnalysis

IMPORT_ANALYSIS_POLICY_VERSION = "import-analysis-policy.v1"


class ImportAnalysisDecision(DomainModel):
    policy_version: Literal["import-analysis-policy.v1"] = "import-analysis-policy.v1"
    route: Literal["confirm", "align", "import"]
    explanation_code: str = Field(min_length=1, max_length=100)
    source_bpm: float | None = Field(default=None, ge=30.0, le=300.0)
    target_bpm: float = Field(ge=30.0, le=300.0)


def decide_import_alignment(
    analysis: ImportedAudioAnalysis,
    *,
    project_bpm: float,
    bpm_confidence_threshold: float = 0.65,
    key_confidence_threshold: float = 0.25,
) -> ImportAnalysisDecision:
    """Route conservatively; infrastructure and numeric decisions never call a model."""

    if (
        analysis.bpm is None
        or analysis.bpm_confidence < bpm_confidence_threshold
        or analysis.key_tonic is None
        or analysis.key_confidence < key_confidence_threshold
    ):
        return ImportAnalysisDecision(
            route="confirm",
            explanation_code="IMPORT_ANALYSIS_LOW_CONFIDENCE",
            source_bpm=analysis.bpm,
            target_bpm=project_bpm,
        )
    delta_ratio = abs(analysis.bpm - project_bpm) / project_bpm
    if delta_ratio <= 0.01:
        return ImportAnalysisDecision(
            route="import",
            explanation_code="IMPORT_BPM_ALREADY_ALIGNED",
            source_bpm=analysis.bpm,
            target_bpm=project_bpm,
        )
    ratio = project_bpm / analysis.bpm
    if not 0.5 <= ratio <= 2.0:
        return ImportAnalysisDecision(
            route="confirm",
            explanation_code="IMPORT_STRETCH_RATIO_REQUIRES_REVIEW",
            source_bpm=analysis.bpm,
            target_bpm=project_bpm,
        )
    return ImportAnalysisDecision(
        route="align",
        explanation_code="IMPORT_BPM_ALIGNMENT_REQUIRED",
        source_bpm=analysis.bpm,
        target_bpm=project_bpm,
    )
