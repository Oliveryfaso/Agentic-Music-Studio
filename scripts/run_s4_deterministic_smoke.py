#!/usr/bin/env python3
"""Run the no-cost public S2 acceptance once for each reviewed S4 Style Pack."""

from __future__ import annotations

import asyncio

from . import run_s2_deterministic_smoke as s2

STYLES = (
    "synth_ambient",
    "minimal_electronic",
    "classical_chamber",
    "jazz_harmony_improvisation",
)


async def main() -> None:
    original = dict(s2.BRIEF)
    try:
        for style in STYLES:
            s2.BRIEF = {
                **original,
                "title": f"S4 deterministic {style}",
                "style": style,
                "duration_seconds": 60,
                "target_bpm": 120,
            }
            await s2.main()
    finally:
        s2.BRIEF = original


if __name__ == "__main__":
    asyncio.run(main())
