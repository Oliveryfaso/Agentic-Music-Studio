"""HTTP read surface for the reviewed local sound catalog."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from motif_forge.agent.schemas import StyleId
from motif_forge.application.sound_catalog import ListLocalSoundCatalog, SoundCatalogQuery
from motif_forge.domain.ir import TrackRole
from motif_forge.domain.style_packs import builtin_style_pack_registry


def build_sound_catalog_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    catalog = ListLocalSoundCatalog(builtin_style_pack_registry())

    @router.get("/sound-catalog")
    async def list_sound_catalog(
        style: StyleId | None = None,
        role: TrackRole | None = None,
        query: Annotated[str, Query(max_length=80)] = "",
    ) -> dict[str, object]:
        entries = catalog(SoundCatalogQuery(style=style, role=role, query=query))
        return {
            "status": "succeeded",
            "data": [item.model_dump(mode="json") for item in entries],
        }

    return router
