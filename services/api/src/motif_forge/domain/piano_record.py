"""Source and request binding for new immutable semantic records; legacy bytes stay unchanged."""

from __future__ import annotations

import json
from typing import Any

from motif_forge.domain.piano_plan import AccompanimentPlanV2, read_piano_plan
from motif_forge.domain.piano_requests import PianoSemanticRequestV2, read_piano_request
from motif_forge.domain.reviewed_scores import REVIEWED_SCORES, ReviewedScore


def piano_source_metadata(source: ReviewedScore) -> dict[str, Any]:
    return {
        "score_id": source.score_id,
        "xml_sha256": source.xml_sha256,
        "beats_per_bar": source.beats,
        "measure_count": source.measures,
    }


def validate_v2_record(record: dict[str, Any]) -> None:
    if record.get("schema_version") != "piano-plan-record.v2":
        raise ValueError("PIANO_PLAN_RECORD_CONTEXT_MISMATCH")
    request = read_piano_request(json.dumps(record["request"]))
    plan = read_piano_plan(json.dumps(record["plan"]))
    if not isinstance(request, PianoSemanticRequestV2) or not isinstance(plan, AccompanimentPlanV2):
        raise ValueError("PIANO_PLAN_RECORD_CONTEXT_MISMATCH")
    source = REVIEWED_SCORES[request.source_score_id]
    if (
        record.get("source") != piano_source_metadata(source)
        or plan.beats_per_bar != request.beats_per_bar
        or tuple(sorted(bar.bar for bar in plan.bars))
        != tuple(range(request.start_bar, request.end_bar + 1))
    ):
        raise ValueError("PIANO_PLAN_RECORD_CONTEXT_MISMATCH")
