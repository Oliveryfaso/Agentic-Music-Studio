"""Strict, reviewed musical knowledge contracts for the four built-in strategies."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Literal, Self, cast

from pydantic import Field, model_validator

from motif_forge.agent.schemas import StyleId
from motif_forge.domain.ir import DomainModel, TrackRole


class LicenseSnapshot(DomainModel):
    license_id: Literal["project-authored", "CC0-1.0", "public-domain"]
    reviewed: Literal[True]
    allows_commercial_use: Literal[True]
    attribution_required: bool


class SourceCitation(DomainModel):
    citation_id: str = Field(pattern=r"^source:[a-z0-9-]+:v1$")
    title: str = Field(min_length=1, max_length=160)
    author: str = Field(min_length=1, max_length=120)
    source_url: str | None = Field(default=None, max_length=320)
    license_id: Literal["project-authored", "CC0-1.0", "public-domain"]


class FormTemplate(DomainModel):
    template_id: str = Field(pattern=r"^form:[a-z0-9-]+:v1$")
    section_functions: tuple[str, ...] = Field(min_length=3, max_length=8)


class InstrumentGuide(DomainModel):
    role: str = Field(min_length=1, max_length=80)
    track_role: TrackRole
    instrument: str = Field(min_length=1, max_length=80)
    low_midi: int = Field(ge=0, le=127)
    high_midi: int = Field(ge=0, le=127)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.high_midi < self.low_midi:
            raise ValueError("instrument high_midi must be at least low_midi")
        return self


class ProductionRecipe(DomainModel):
    recipe_id: str = Field(pattern=r"^recipe:[a-z0-9-]+:v1$")
    summary: str = Field(min_length=1, max_length=240)


class SymbolicExemplar(DomainModel):
    exemplar_id: str = Field(pattern=r"^exemplar:[a-z0-9-]+:v1$")
    source_citation_id: str = Field(pattern=r"^source:[a-z0-9-]+:v1$")
    derived_facts: tuple[str, ...] = Field(min_length=1, max_length=12)


class PresetEntry(DomainModel):
    preset_id: str = Field(pattern=r"^builtin:[a-z0-9-]+$")
    instrument_family: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    low_midi: int = Field(ge=0, le=127)
    high_midi: int = Field(ge=0, le=127)
    reviewed: Literal[True]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.high_midi < self.low_midi:
            raise ValueError("preset high_midi must be at least low_midi")
        return self


class StylePack(DomainModel):
    schema_version: Literal["style-pack.v1"] = "style-pack.v1"
    pack_id: str = Field(pattern=r"^style:[a-z0-9-]+:v1$")
    version: Literal["v1"] = "v1"
    style: StyleId
    genre: str = Field(min_length=1, max_length=80)
    era: str = Field(min_length=1, max_length=120)
    compatible_plan_schema_versions: tuple[Literal["composition-plan.v1"], ...] = (
        "composition-plan.v1",
    )
    compatible_engine_versions: tuple[Literal["theory-engine.v1"], ...] = (
        "theory-engine.v1",
    )
    form_templates: tuple[FormTemplate, ...] = Field(min_length=1)
    instrumentation: tuple[InstrumentGuide, ...] = Field(min_length=4, max_length=4)
    harmony_constraints: tuple[str, ...] = Field(min_length=1)
    rhythm_constraints: tuple[str, ...] = Field(min_length=1)
    timbre_constraints: tuple[str, ...] = Field(min_length=1)
    avoidances: tuple[str, ...] = Field(min_length=1)
    production_recipes: tuple[ProductionRecipe, ...] = Field(min_length=1)
    symbolic_exemplars: tuple[SymbolicExemplar, ...] = Field(min_length=1)
    sources: tuple[SourceCitation, ...] = Field(min_length=1)
    license_snapshot: LicenseSnapshot
    preset_palette: tuple[PresetEntry, ...] = Field(min_length=4)

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        roles = tuple(item.track_role for item in self.instrumentation)
        required_roles = {
            TrackRole.HARMONY,
            TrackRole.MELODY,
            TrackRole.BASS,
            TrackRole.RHYTHM,
        }
        if set(roles) != required_roles or len(set(roles)) != 4:
            raise ValueError("a Style Pack must map exactly one instrument to each export role")
        citation_ids = {item.citation_id for item in self.sources}
        if any(item.source_citation_id not in citation_ids for item in self.symbolic_exemplars):
            raise ValueError("symbolic exemplar citation is not present in sources")
        instrument_roles = {item.role for item in self.instrumentation}
        if any(item.role not in instrument_roles for item in self.preset_palette):
            raise ValueError("preset role is not declared by instrumentation")
        return self


class StylePackRegistry:
    def __init__(self, packs: tuple[StylePack, ...]) -> None:
        by_style = {pack.style: pack for pack in packs}
        if len(packs) != 4 or len(by_style) != 4:
            raise ValueError("the built-in registry requires exactly one pack for each style")
        self._packs = by_style

    @property
    def styles(self) -> tuple[StyleId, ...]:
        return cast(tuple[StyleId, ...], tuple(self._packs))

    def resolve(self, style: StyleId) -> StylePack:
        try:
            return self._packs[style]
        except KeyError as exc:
            raise KeyError(f"Style Pack is not registered: {style}") from exc


def builtin_style_pack_registry() -> StylePackRegistry:
    resource = files("motif_forge.knowledge").joinpath("style_packs.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    packs = tuple(
        StylePack.model_validate_json(json.dumps(item), strict=True) for item in payload
    )
    return StylePackRegistry(packs)
