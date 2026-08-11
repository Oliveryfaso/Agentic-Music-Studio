"""Deterministic PPQ time conversion helpers for ArrangementIR v1."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from motif_forge.domain.ir import PPQ


def ticks_to_beats(ticks: int, *, ppq: int = PPQ) -> Decimal:
    """Convert quarter-note ticks to beats without binary floating-point drift."""

    if ticks < 0:
        raise ValueError("ticks must be non-negative")
    if ppq <= 0:
        raise ValueError("ppq must be positive")
    return Decimal(ticks) / Decimal(ppq)


def beats_to_ticks(beats: Decimal | int | str, *, ppq: int = PPQ) -> int:
    """Convert beats to the nearest tick using an explicit half-up policy."""

    value = Decimal(beats)
    if value < 0:
        raise ValueError("beats must be non-negative")
    if ppq <= 0:
        raise ValueError("ppq must be positive")
    return int((value * Decimal(ppq)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ticks_to_seconds(ticks: int, *, bpm: Decimal | int | str, ppq: int = PPQ) -> Decimal:
    """Convert ticks to seconds at a constant tempo."""

    tempo = Decimal(bpm)
    if tempo <= 0:
        raise ValueError("bpm must be positive")
    return ticks_to_beats(ticks, ppq=ppq) * Decimal(60) / tempo


def seconds_to_ticks(
    seconds: Decimal | int | str,
    *,
    bpm: Decimal | int | str,
    ppq: int = PPQ,
) -> int:
    """Convert seconds to the nearest tick at a constant tempo."""

    duration = Decimal(seconds)
    tempo = Decimal(bpm)
    if duration < 0:
        raise ValueError("seconds must be non-negative")
    if tempo <= 0:
        raise ValueError("bpm must be positive")
    beats = duration * tempo / Decimal(60)
    return beats_to_ticks(beats, ppq=ppq)
