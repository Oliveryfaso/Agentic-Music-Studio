"""Canonical serialization and content hashing for immutable arrangements."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from motif_forge.domain.ir import ArrangementIR

FLOAT_PRECISION = 6

_IDENTITY_KEYS = (
    "track_id",
    "clip_id",
    "note_id",
    "section_id",
    "marker_id",
)


def _list_sort_key(item: Any) -> tuple[str, ...]:
    if not isinstance(item, dict):
        return (json.dumps(item, sort_keys=True, separators=(",", ":")),)
    for key in _IDENTITY_KEYS:
        if key in item:
            return (key, str(item[key]))
    if "tick" in item:
        return ("tick", f"{int(item['tick']):020d}")
    if "start_tick" in item and "end_tick" in item:
        return (
            "range",
            f"{int(item['start_tick']):020d}",
            f"{int(item['end_tick']):020d}",
        )
    if "kind" in item and "ref" in item:
        return ("provenance", str(item["kind"]), str(item["ref"]), str(item.get("version")))
    return (json.dumps(item, sort_keys=True, separators=(",", ":")),)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_normalize(item) for item in value]
        return sorted(normalized, key=_list_sort_key)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON cannot contain NaN or Infinity")
        rounded = round(value, FLOAT_PRECISION)
        return 0.0 if rounded == 0.0 else rounded
    return value


def canonical_dict(arrangement: ArrangementIR) -> dict[str, Any]:
    """Return a recursively normalized JSON-compatible representation."""

    dumped = arrangement.model_dump(mode="json", exclude_none=False)
    normalized = _normalize(dumped)
    if not isinstance(normalized, dict):  # pragma: no cover - defensive invariant
        raise TypeError("ArrangementIR must serialize to an object")
    return normalized


def canonical_json_bytes(arrangement: ArrangementIR) -> bytes:
    """Serialize an arrangement to stable UTF-8 JSON bytes."""

    return json.dumps(
        canonical_dict(arrangement),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def arrangement_content_hash(arrangement: ArrangementIR) -> str:
    """Return the SHA-256 digest of canonical ArrangementIR bytes."""

    return hashlib.sha256(canonical_json_bytes(arrangement)).hexdigest()
