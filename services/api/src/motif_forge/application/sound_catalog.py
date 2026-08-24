"""Read-only projection of reviewed presets from the built-in Style Packs."""

from __future__ import annotations

from pydantic import Field

from motif_forge.agent.schemas import StyleId
from motif_forge.domain.ir import DomainModel, TrackRole
from motif_forge.domain.style_packs import StylePackRegistry


class SoundCatalogQuery(DomainModel):
    style: StyleId | None = None
    role: TrackRole | None = None
    query: str = Field(default="", max_length=80)


class SoundCatalogEntry(DomainModel):
    preset_id: str
    style: StyleId
    instrument_family: str
    role: str
    low_midi: int
    high_midi: int
    reviewed: bool
    license_id: str
    attribution_required: bool


class ListLocalSoundCatalog:
    def __init__(self, registry: StylePackRegistry) -> None:
        self._registry = registry

    def __call__(self, query: SoundCatalogQuery) -> tuple[SoundCatalogEntry, ...]:
        normalized = query.query.casefold().strip()
        styles = (query.style,) if query.style is not None else self._registry.styles
        entries: list[SoundCatalogEntry] = []
        for style in styles:
            pack = self._registry.resolve(style)
            for preset in pack.preset_palette:
                if query.role is not None:
                    guide = next(item for item in pack.instrumentation if item.role == preset.role)
                    if guide.track_role is not query.role:
                        continue
                searchable = (
                    f"{preset.preset_id} {preset.instrument_family} {preset.role}"
                ).casefold()
                if normalized and normalized not in searchable:
                    continue
                entries.append(
                    SoundCatalogEntry(
                        preset_id=preset.preset_id,
                        style=style,
                        instrument_family=preset.instrument_family,
                        role=preset.role,
                        low_midi=preset.low_midi,
                        high_midi=preset.high_midi,
                        reviewed=preset.reviewed,
                        license_id=pack.license_snapshot.license_id,
                        attribution_required=pack.license_snapshot.attribution_required,
                    )
                )
        return tuple(sorted(entries, key=lambda item: (item.style, item.preset_id)))
