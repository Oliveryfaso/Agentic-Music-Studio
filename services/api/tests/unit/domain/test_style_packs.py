import pytest
from motif_forge.domain.style_packs import (
    LicenseSnapshot,
    StylePackRegistry,
    builtin_style_pack_registry,
)
from pydantic import ValidationError

EXPECTED_STYLES = {
    "synth_ambient",
    "minimal_electronic",
    "classical_chamber",
    "jazz_harmony_improvisation",
}


def test_builtin_registry_contains_four_reviewed_distinct_packs() -> None:
    registry = builtin_style_pack_registry()

    assert set(registry.styles) == EXPECTED_STYLES
    assert len({registry.resolve(style).pack_id for style in EXPECTED_STYLES}) == 4
    for style in EXPECTED_STYLES:
        pack = registry.resolve(style)  # type: ignore[arg-type]
        assert pack.version == "v1"
        assert pack.compatible_plan_schema_versions == ("composition-plan.v1",)
        assert pack.compatible_engine_versions == ("theory-engine.v1",)
        assert len(pack.instrumentation) == 4
        assert {item.track_role for item in pack.instrumentation} == {
            "harmony", "melody", "bass", "rhythm"
        }
        assert pack.sources and pack.symbolic_exemplars and pack.preset_palette
        assert pack.license_snapshot.reviewed is True
        assert pack.license_snapshot.allows_commercial_use is True


def test_license_snapshot_rejects_unreviewed_or_nc_knowledge() -> None:
    with pytest.raises(ValidationError):
        LicenseSnapshot(
            license_id="CC-BY-NC-4.0",
            reviewed=False,
            allows_commercial_use=False,
            attribution_required=True,
        )


def test_registry_fails_closed_for_missing_or_duplicate_style() -> None:
    registry = builtin_style_pack_registry()
    synth = registry.resolve("synth_ambient")

    with pytest.raises(ValueError, match="exactly one pack"):
        StylePackRegistry((synth, synth))
    with pytest.raises(KeyError, match="not registered"):
        registry.resolve("not_a_style")  # type: ignore[arg-type]


def test_instrument_and_preset_ranges_are_playable_and_linked() -> None:
    registry = builtin_style_pack_registry()

    for style in EXPECTED_STYLES:
        pack = registry.resolve(style)  # type: ignore[arg-type]
        instrument_roles = {item.role for item in pack.instrumentation}
        for instrument in pack.instrumentation:
            assert 0 <= instrument.low_midi <= instrument.high_midi <= 127
        for preset in pack.preset_palette:
            assert preset.reviewed is True
            assert preset.role in instrument_roles
            assert 0 <= preset.low_midi <= preset.high_midi <= 127
