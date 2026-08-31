"""Public read-only Generate Graph projection route."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from motif_forge.application.run_graph import ReadRunGraph, RunGraphReadModel


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunGraphResponse(ApiModel):
    data: RunGraphReadModel


def build_run_graph_router(read_run_graph: ReadRunGraph) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["run-graph"])

    @router.get("/runs/{run_id}/graph", response_model=RunGraphResponse)
    async def read_graph(run_id: UUID) -> RunGraphResponse:
        return RunGraphResponse(data=await read_run_graph(run_id))

    return router
