"""Deterministic fixtures for infrastructure-only integration tests."""

from typing import Any


def valid_brief_payload() -> dict[str, Any]:
    return {
        "schema_version": "composition-brief.v1",
        "title": "Orbital Glass",
        "purpose": "Instrumental background for a science-fiction puzzle",
        "style": "synth_ambient",
        "duration_seconds": 120,
        "meter": "4/4",
        "target_bpm": 72,
        "target_key": "D dorian",
        "moods": ["weightless", "curious"],
        "preferred_instruments": ["warm pad", "soft pulse"],
        "hard_constraints": ["avoid clipping"],
        "soft_preferences": ["leave room for narration"],
        "negative_constraints": ["no abrupt drop"],
    }


def valid_plan_payload() -> dict[str, Any]:
    return {
        "schema_version": "composition-plan.v1",
        "genre": "synth_ambient",
        "era_influences": ["modern ambient"],
        "purpose": "Instrumental background for a science-fiction puzzle",
        "moods": ["weightless", "curious"],
        "duration_bars": 32,
        "bpm": 72,
        "meter": "4/4",
        "key": {"tonic": "D", "mode": "dorian"},
        "sections": [
            {
                "section_id": "opening",
                "name": "Opening",
                "start_bar": 0,
                "end_bar": 8,
                "function": "Establish the harmonic field",
                "energy": 0.25,
            },
            {
                "section_id": "development",
                "name": "Development",
                "start_bar": 8,
                "end_bar": 24,
                "function": "Develop the pulse and motif",
                "energy": 0.6,
            },
            {
                "section_id": "resolution",
                "name": "Resolution",
                "start_bar": 24,
                "end_bar": 32,
                "function": "Reduce density and resolve",
                "energy": 0.2,
            },
        ],
        "instrumentation": [
            {
                "instrument_id": "warm_pad",
                "name": "Warm Pad",
                "role": "harmonic bed",
                "pitch_range": "low-mid to high-mid",
                "entry_section_id": "opening",
                "exit_section_id": "resolution",
            },
            {
                "instrument_id": "soft_pulse",
                "name": "Soft Pulse",
                "role": "rhythmic motion",
                "pitch_range": "mid",
                "entry_section_id": "development",
                "exit_section_id": "resolution",
            },
        ],
        "harmonic_language": "Open fifths with restrained D dorian color tones",
        "rhythmic_language": "Sparse eighth-note pulses with gradual subdivision",
        "texture": "Layered pads with a narrow pulse and long controlled tails",
        "hard_constraints": ["avoid clipping"],
        "soft_preferences": ["leave room for narration"],
        "negative_constraints": ["no abrupt drop"],
        "knowledge_references": [
            {
                "reference_id": "style:synth-ambient:v1",
                "summary": "Use slow spectral motion and restrained density",
                "confidence": 0.9,
            }
        ],
        "confidence": 0.88,
    }
