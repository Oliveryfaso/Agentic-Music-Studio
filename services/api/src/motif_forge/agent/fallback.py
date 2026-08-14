"""Deterministic, deliberately conservative CompositionPlan fallback."""

from __future__ import annotations

import math

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, KeyPlan

_STYLE_DEFAULTS: dict[str, tuple[int, tuple[str, ...], str, str, str]] = {
    "synth_ambient": (
        72,
        ("Warm Pad", "Glass Pluck", "Sub Bass", "Soft Pulse"),
        "Open fifths with restrained modal color",
        "Sparse pulses with gradual subdivision",
        "Layered pads with controlled tails",
    ),
    "minimal_electronic": (
        112,
        ("Drum Machine", "Mono Bass", "Poly Synth"),
        "Short diatonic loop with one color tone",
        "Stable sixteenth-note grid with restrained syncopation",
        "Dry groove with one contrasting synth layer",
    ),
    "classical_chamber": (
        84,
        ("Violin", "Viola", "Cello"),
        "Functional diatonic harmony with clear cadences",
        "Phrase-led pulse with limited rhythmic density",
        "Three-part chamber texture with register separation",
    ),
    "jazz_harmony_improvisation": (
        108,
        ("Piano", "Upright Bass", "Brush Kit"),
        "Guide-tone voice leading with bounded diatonic tensions",
        "Light swing grid with phrase-level syncopation",
        "Compact rhythm section supporting a single melodic voice",
    ),
}

_SYNTH_AMBIENT_ROLES = ("pad", "melody", "bass", "rhythm")


def _key_from_brief(target_key: str | None) -> dict[str, str]:
    if target_key:
        parts = target_key.replace("-", " ").split()
        tonic = parts[0] if parts else "C"
        mode = parts[1].lower() if len(parts) > 1 else "major"
        candidate = {"tonic": tonic, "mode": mode}
        try:
            return KeyPlan.model_validate(candidate, strict=True).model_dump(mode="json")
        except ValueError:
            pass
    return {"tonic": "C", "mode": "major"}


def build_fallback_plan(brief: CompositionBrief) -> CompositionPlan:
    """Build a playable macro plan without pretending it is model-authored."""

    default_bpm, default_instruments, harmony, rhythm, texture = _STYLE_DEFAULTS[brief.style]
    bpm = brief.target_bpm or default_bpm
    beats_per_bar = 3 if brief.meter == "3/4" else 4
    raw_bars = brief.duration_seconds * bpm / (60 * beats_per_bar)
    duration_bars = min(256, max(8, int(math.ceil(raw_bars / 4) * 4)))
    opening_end = max(4, duration_bars // 4)
    closing_start = min(duration_bars - 4, max(opening_end + 4, duration_bars * 3 // 4))
    if closing_start >= duration_bars:
        closing_start = duration_bars - 2
    if opening_end >= closing_start:
        opening_end = max(1, duration_bars // 3)
        closing_start = max(opening_end + 1, duration_bars * 2 // 3)

    preferred = brief.preferred_instruments
    instrument_names = tuple(
        preferred[index] if index < len(preferred) else name
        for index, name in enumerate(default_instruments)
    )
    if brief.style == "synth_ambient":
        instrumentation = tuple(
            {
                "instrument_id": f"fallback_instrument_{index}",
                "name": name,
                "role": role,
                "pitch_range": "supported built-in range",
                "entry_section_id": "opening",
                "exit_section_id": "resolution",
            }
            for index, (name, role) in enumerate(
                zip(instrument_names, _SYNTH_AMBIENT_ROLES, strict=True), start=1
            )
        )
    else:
        instrumentation = tuple(
            {
                "instrument_id": f"fallback_instrument_{index}",
                "name": name,
                "role": "primary arrangement layer" if index == 1 else "supporting layer",
                "pitch_range": "supported preset range",
                "entry_section_id": "opening" if index == 1 else "development",
                "exit_section_id": "resolution",
            }
            for index, name in enumerate(instrument_names[:12], start=1)
        )
    payload = {
        "schema_version": "composition-plan.v1",
        "genre": brief.style,
        "era_influences": (),
        "purpose": brief.purpose,
        "moods": brief.moods,
        "duration_bars": duration_bars,
        "bpm": bpm,
        "meter": brief.meter,
        "key": _key_from_brief(brief.target_key),
        "sections": (
            {
                "section_id": "opening",
                "name": "Opening",
                "start_bar": 0,
                "end_bar": opening_end,
                "function": "Establish the core palette and pulse",
                "energy": 0.25,
            },
            {
                "section_id": "development",
                "name": "Development",
                "start_bar": opening_end,
                "end_bar": closing_start,
                "function": "Develop density and motif while preserving the brief",
                "energy": 0.6,
            },
            {
                "section_id": "resolution",
                "name": "Resolution",
                "start_bar": closing_start,
                "end_bar": duration_bars,
                "function": "Reduce density and provide a clear ending",
                "energy": 0.2,
            },
        ),
        "instrumentation": instrumentation,
        "harmonic_language": harmony,
        "rhythmic_language": rhythm,
        "texture": texture,
        "hard_constraints": brief.hard_constraints,
        "soft_preferences": brief.soft_preferences,
        "negative_constraints": brief.negative_constraints,
        "knowledge_references": (),
        "confidence": 0.35,
    }
    return CompositionPlan.model_validate(payload, strict=True)
