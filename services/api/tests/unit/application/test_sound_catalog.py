import pytest
from motif_forge.application.sound_catalog import ListLocalSoundCatalog, SoundCatalogQuery
from motif_forge.domain.ir import TrackRole
from motif_forge.domain.style_packs import builtin_style_pack_registry
from pydantic import ValidationError


def test_local_catalog_returns_only_reviewed_builtin_entries() -> None:
    entries = ListLocalSoundCatalog(builtin_style_pack_registry())(
        SoundCatalogQuery(
            style="jazz_harmony_improvisation", role=TrackRole.BASS, query="bass"
        )
    )
    assert entries
    assert all(item.preset_id.startswith("builtin:") for item in entries)
    assert all(
        item.reviewed
        and item.license_id in {"project-authored", "CC0-1.0", "public-domain"}
        for item in entries
    )


def test_catalog_query_rejects_external_provider_fields() -> None:
    with pytest.raises(ValidationError):
        SoundCatalogQuery.model_validate({"external": True, "url": "https://example.test"})
