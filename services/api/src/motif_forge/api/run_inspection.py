"""Public read-only Run Inspector route."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from motif_forge.application.run_inspection import (
    ReadAIRunInspection,
    RunInspectionFacts,
    RunInspectionStore,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunInspectionResponse(ApiModel):
    data: RunInspectionFacts


def build_run_inspection_router(store: RunInspectionStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["run-inspection"])

    @router.get("/runs/{run_id}/inspect", response_model=RunInspectionResponse)
    async def read_run_inspection(run_id: UUID) -> RunInspectionResponse:
        return RunInspectionResponse(data=await ReadAIRunInspection(store)(run_id))

    return router
