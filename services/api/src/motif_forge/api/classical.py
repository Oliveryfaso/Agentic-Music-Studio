"""Reviewed classical score entry; fixed source IDs, no arbitrary path or download."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel

from motif_forge.application.classical_import import (
    ClassicalScoreRequest,
    ClassicalScoreResult,
    CreateClassicalScore,
    read_classical_source,
    reviewed_score,
)
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.classical_score import ScoreNote
from motif_forge.domain.reviewed_scores import REVIEWED_SCORES


class ClassicalScoreDescription(BaseModel):
    score_id: str
    title: str
    composer: str
    digital_editor: str
    license: str
    source_url: str
    page_url: str
    original_sha256: str
    musicxml_sha256: str
    conversion: str
    measure_count: int
    note_count: int
    default_chords: tuple[str, ...]
    beats: int
    bpm: float
    tonic: str


class ClassicalCatalogResponse(BaseModel):
    data: tuple[ClassicalScoreDescription, ...]


class ClassicalCreateResponse(BaseModel):
    data: ClassicalScoreResult


class ClassicalImportReport(BaseModel):
    measure_count: int
    note_count: int
    bpm: float
    beats: int
    tonic: str
    rest_tail_bars: int
    note_map: tuple[ScoreNote, ...]


class ClassicalSourceData(BaseModel):
    project_id: UUID
    revision_id: UUID
    source_branch_id: UUID
    source: ClassicalScoreDescription
    import_report: ClassicalImportReport


class ClassicalSourceResponse(BaseModel):
    data: ClassicalSourceData


def describe(manifest: dict[str, Any]) -> ClassicalScoreDescription:
    return ClassicalScoreDescription(
        score_id=manifest["score_id"],
        title=manifest["title"],
        composer=manifest["composer"],
        digital_editor=manifest["digital_editor"],
        license=manifest["license"],
        source_url=manifest["url"],
        page_url=manifest["page"],
        original_sha256=manifest["sha256"],
        musicxml_sha256=manifest["musicxml_sha256"],
        conversion=manifest["conversion"],
        measure_count=manifest["measures"],
        note_count=manifest["note_count"],
        default_chords=tuple(manifest["default_chords"]),
        beats=manifest.get("beats", 4),
        bpm=manifest.get("bpm", 100),
        tonic=manifest.get("tonic", "G"),
    )


def build_classical_router(
    projects: UnitOfWorkFactory | None, *, capability: Callable[[], Awaitable[PianoCapability]]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["classical-score"])

    @router.get("/classical-scores", response_model=ClassicalCatalogResponse)
    async def catalog() -> ClassicalCatalogResponse:
        return ClassicalCatalogResponse(
            data=tuple(describe(reviewed_score(score_id)[0]) for score_id in REVIEWED_SCORES)
        )

    @router.get("/classical-scores/{score_id}/musicxml")
    async def musicxml(score_id: str) -> Response:
        _, data = reviewed_score(score_id)
        return Response(
            data,
            media_type="application/vnd.recordare.musicxml+xml",
            headers={"Content-Disposition": f'attachment; filename="{score_id}.musicxml"'},
        )

    @router.post(
        "/classical-score-imports", response_model=ClassicalCreateResponse, status_code=201
    )
    async def create(
        body: ClassicalScoreRequest,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
        ],
    ) -> ClassicalCreateResponse:
        if projects is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED", "Score import requires persistence."
            )
        return ClassicalCreateResponse(
            data=await CreateClassicalScore(projects, capability)(
                body, idempotency_key=idempotency_key
            )
        )

    @router.get("/projects/{project_id}/classical-source", response_model=ClassicalSourceResponse)
    async def source(project_id: UUID) -> ClassicalSourceResponse:
        if projects is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED", "Score import requires persistence."
            )
        value = await read_classical_source(projects, project_id)
        value["source"] = describe(value["source"]).model_dump(mode="json")
        return ClassicalSourceResponse(
            data=ClassicalSourceData.model_validate_json(json.dumps(value), strict=True)
        )

    return router
