"""Explicit register locks for bounded piano edits; never repair model notes."""

from __future__ import annotations

import re

from motif_forge.domain.piano_plan import PianoPlan

REGISTER_POLICY_VERSION = "piano-register-preserved.v1"


def register_preservation_requested(intent: str) -> bool:
    """Recognize explicit keep-register clauses, not a general intent interpreter."""
    clauses = re.split(r"[\uff0c,\uff1b;。.!?\uff01\uff1f\n]", intent)
    keep = False
    for clause in clauses:
        if re.search(
            r"(?:不保留|不要保持|无需(?:保持|保留)|不必(?:保持|保留)|不维持).*音区"
            r"|(?:do not|don't|no need to).*\b(?:keep|preserve|retain)\b.*\bregister\b",
            clause,
            re.IGNORECASE,
        ):
            raise ValueError("PIANO_REGISTER_INTENT_UNSUPPORTED")
        keep |= bool(
            re.search(
                r"(?:保留|保持|维持).*音区|音区(?:保持|维持)?(?:不变|固定|不能变)|不改变(?:原)?音区"
                r"|\b(?:keep|preserve|retain)\b.*\bregister\b|\bregister\s+unchanged\b",
                clause,
                re.IGNORECASE,
            )
        )
    direction_text = re.sub(r"(?:不|不要|无需|勿|不能)(?:改变|调整|移动)(?:原)?音区", "", intent)
    shifts = re.search(
        r"(?:提高|升高|降低|上移|下移|改变|调整|移动)(?:(?!(?:力度|音量|密度|保留|保持)).){0,12}(?:音区|八度)"
        r"|(?:升|降)(?:高|低)?(?:一|一个|两|两个)?八度"
        r"|\b(?:raise|lower|shift|change)\b"
        r"(?:(?!(?:volume|velocity|density|keep|preserve)).){0,30}\b(?:register|octave)\b",
        direction_text,
        re.IGNORECASE,
    )
    if keep and shifts:
        raise ValueError("PIANO_REGISTER_INTENT_UNSUPPORTED")
    return keep


def validate_preserved_register(plan: PianoPlan, register: dict[int, int]) -> None:
    if {bar.bar: bar.octave for bar in plan.bars} != register:
        raise ValueError("PIANO_REGISTER_CHANGED")
