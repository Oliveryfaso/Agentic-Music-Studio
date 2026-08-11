from collections.abc import Callable
from decimal import Decimal

import pytest
from motif_forge.domain import (
    beats_to_ticks,
    seconds_to_ticks,
    ticks_to_beats,
    ticks_to_seconds,
)


def test_ppq_time_conversions_are_deterministic_and_round_trip() -> None:
    assert ticks_to_beats(1_920) == Decimal("4")
    assert beats_to_ticks("4") == 1_920
    assert ticks_to_seconds(1_920, bpm=120) == Decimal("2")
    assert seconds_to_ticks("2", bpm=120) == 1_920


def test_fractional_tick_rounding_is_explicit_half_up() -> None:
    assert beats_to_ticks(Decimal("0.001")) == 0
    assert beats_to_ticks(Decimal("0.0010416666666666667")) == 1


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: ticks_to_beats(-1), "ticks must be non-negative"),
        (lambda: ticks_to_seconds(0, bpm=0), "bpm must be positive"),
        (lambda: seconds_to_ticks("-0.1", bpm=120), "seconds must be non-negative"),
    ],
)
def test_time_conversions_reject_invalid_ranges(call: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()
