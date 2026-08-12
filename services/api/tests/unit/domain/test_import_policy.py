from motif_forge.domain.import_policy import decide_import_alignment
from motif_forge.domain.media_jobs import ImportedAudioAnalysis


def _analysis(**updates: object) -> ImportedAudioAnalysis:
    values: dict[str, object] = {
        "bpm": 100.0,
        "bpm_confidence": 0.9,
        "key_tonic": "C",
        "key_mode": "major",
        "key_confidence": 0.8,
        "analyzed_seconds": 30.0,
    }
    values.update(updates)
    return ImportedAudioAnalysis.model_validate(values)


def test_confident_bpm_mismatch_routes_to_pitch_preserving_alignment() -> None:
    decision = decide_import_alignment(_analysis(), project_bpm=120)

    assert decision.route == "align"
    assert decision.source_bpm == 100


def test_low_key_confidence_routes_to_human_even_with_confident_bpm() -> None:
    decision = decide_import_alignment(
        _analysis(key_tonic=None, key_mode=None, key_confidence=0.0), project_bpm=120
    )

    assert decision.route == "confirm"
    assert decision.explanation_code == "IMPORT_ANALYSIS_LOW_CONFIDENCE"


def test_already_aligned_bpm_skips_derived_audio() -> None:
    decision = decide_import_alignment(_analysis(bpm=120.5), project_bpm=120)

    assert decision.route == "import"
