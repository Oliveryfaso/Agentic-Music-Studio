"""Canonical request fingerprints used by idempotent writes."""

from __future__ import annotations

import hashlib
import json


def request_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
