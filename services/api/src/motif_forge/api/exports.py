"""Public S7 Export read and delivery routes."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Header, Query
from fastapi.responses import FileResponse
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, model_validator

from motif_forge.agent.parent_graph import initial_export_state
from motif_forge.application.errors import ApplicationError
from motif_forge.application.export_reads import (
    ExportProjectionStore,
    ReadRevisionExport,
    ResolveBundleFile,
    RevisionExportProjection,
)
from motif_forge.application.revision_exports import RevisionExportRequest
from motif_forge.domain.export_plan import ExportPlanV2


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RevisionExportResponse(ApiModel):
    data: RevisionExportProjection


class RevisionExportOptions(ApiModel):
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    include_mp3: bool = True
    include_all_stems: bool = False
    stem_track_ids: tuple[UUID, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def validate_stems(self) -> RevisionExportOptions:
        if self.include_all_stems and self.stem_track_ids:
            raise ValueError("EXPORT_STEM_SELECTION_AMBIGUOUS")
        if len(set(self.stem_track_ids)) != len(self.stem_track_ids):
            raise ValueError("EXPORT_TRACK_IDS_NOT_CANONICAL")
        return self


class RevisionExportRunData(ApiModel):
    thread_id: str
    phase: str
    plan_hash: str | None = None
    export_plan: ExportPlanV2 | None = None
    media_run_id: UUID | None = None
    pending_job_id: UUID | None = None
    bundle_artifact_id: UUID | None = None
    error_code: str | None = None
    replayed: bool = False


class RevisionExportRunResponse(ApiModel):
    data: RevisionExportRunData


def _run_data(
    values: Mapping[str, Any], *, thread_id: str, replayed: bool = False
) -> RevisionExportRunResponse:
    cursor = values.get("export_cursor", {})
    return RevisionExportRunResponse(
        data=RevisionExportRunData(
            thread_id=thread_id,
            phase=values["phase"],
            plan_hash=values.get("plan_hash"),
            export_plan=ExportPlanV2.model_validate_json(json.dumps(cursor["plan"]), strict=True)
            if cursor.get("plan")
            else None,
            media_run_id=values.get("media_run_id"),
            pending_job_id=values.get("pending_job_id"),
            bundle_artifact_id=cursor.get("bundle_artifact_id"),
            error_code=values.get("error_code"),
            replayed=replayed,
        )
    )


def build_export_router(
    store: ExportProjectionStore,
    *,
    artifact_root: Path,
    graph_getter: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["exports"])

    @router.get(
        "/projects/{project_id}/revisions/{revision_id}/exports",
        response_model=RevisionExportResponse,
    )
    async def read_revision_export(
        project_id: UUID,
        revision_id: UUID,
        plan_hash: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
    ) -> RevisionExportResponse:
        return RevisionExportResponse(
            data=await ReadRevisionExport(store)(
                project_id=project_id, revision_id=revision_id, plan_hash=plan_hash
            )
        )

    def configured_graph() -> Any:
        graph = graph_getter() if graph_getter is not None else None
        if graph is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED", "exports require persistent Parent checkpoints"
            )
        return graph

    @router.post(
        "/projects/{project_id}/revisions/{revision_id}/exports",
        response_model=RevisionExportRunResponse,
        status_code=202,
    )
    async def start_export(
        project_id: UUID,
        revision_id: UUID,
        body: RevisionExportOptions,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
        ],
    ) -> RevisionExportRunResponse:
        graph = configured_graph()
        identity = f"{project_id}:{idempotency_key}"
        thread_id = "export-" + sha256(identity.encode()).hexdigest()[:32]
        request = RevisionExportRequest.model_validate_json(
            json.dumps(
                {
                    **body.model_dump(mode="json"),
                    "project_id": str(project_id),
                    "revision_id": str(revision_id),
                    "request_id": str(uuid5(NAMESPACE_URL, identity)),
                }
            ),
            strict=True,
        )
        state = initial_export_state(thread_id=thread_id, request=request)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        replayed = bool(snapshot.values)
        if replayed:
            if any(
                snapshot.values.get(key) != dict(state)[key]
                for key in ("operation", "project_id", "request_payload")
            ):
                raise ApplicationError(
                    "IDEMPOTENCY_KEY_REUSED", "the key was used with a different export request"
                )
            values = snapshot.values
            # A failed/interrupted node can leave a durable checkpoint without an
            # interrupt. Resume that node; its application transaction is idempotent.
            if (
                snapshot.next
                and not values.get("terminal_status")
                and not any(task.interrupts for task in snapshot.tasks)
            ):
                values = await graph.ainvoke(None, config)
        else:
            values = await graph.ainvoke(state, config)
        if values.get("phase") == "failed" and not values.get("media_run_id"):
            raise ApplicationError(
                values.get("error_code", "EXPORT_REQUEST_INVALID"),
                "export request could not be prepared",
            )
        return _run_data(values, thread_id=thread_id, replayed=replayed)

    async def scoped_snapshot(
        project_id: UUID, revision_id: UUID, thread_id: str
    ) -> tuple[Any, Any, dict[str, Any]]:
        graph = configured_graph()
        if not thread_id.startswith("export-") or len(thread_id) != 39:
            raise ApplicationError("EXPORT_RUN_NOT_FOUND", "export Run not found")
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        values = snapshot.values
        if (
            values.get("operation") != "export"
            or values.get("project_id") != str(project_id)
            or values.get("request_payload", {}).get("revision_id") != str(revision_id)
        ):
            raise ApplicationError(
                "EXPORT_RUN_NOT_FOUND", "export Run does not belong to the revision"
            )
        return graph, snapshot, config

    @router.get(
        "/projects/{project_id}/revisions/{revision_id}/export-runs/{thread_id}",
        response_model=RevisionExportRunResponse,
    )
    async def read_export_run(
        project_id: UUID, revision_id: UUID, thread_id: str
    ) -> RevisionExportRunResponse:
        _, snapshot, _ = await scoped_snapshot(project_id, revision_id, thread_id)
        response = _run_data(snapshot.values, thread_id=thread_id)
        if response.data.plan_hash:
            projection = await ReadRevisionExport(store)(
                project_id=project_id, revision_id=revision_id, plan_hash=response.data.plan_hash
            )
            if projection.status == "cancelled":
                return response.model_copy(
                    update={
                        "data": response.data.model_copy(
                            update={"phase": "cancelled", "pending_job_id": None}
                        )
                    }
                )
        return response

    @router.post(
        "/projects/{project_id}/revisions/{revision_id}/export-runs/{thread_id}/cancel",
        response_model=RevisionExportRunResponse,
    )
    async def cancel_export_run(
        project_id: UUID, revision_id: UUID, thread_id: str
    ) -> RevisionExportRunResponse:
        graph, snapshot, config = await scoped_snapshot(project_id, revision_id, thread_id)
        if snapshot.values.get("terminal_status") is not None:
            return _run_data(snapshot.values, thread_id=thread_id, replayed=True)
        if snapshot.values.get("phase") != "waiting_export_worker":
            raise ApplicationError(
                "EXPORT_RUN_STATE_CONFLICT", "export is not at a cancellable boundary"
            )
        result = await graph.ainvoke(Command(resume={"action": "cancel"}), config)
        return _run_data(result, thread_id=thread_id)

    @router.get("/export-bundles/{bundle_id}/files/{filename}", response_class=FileResponse)
    async def read_bundle_file(bundle_id: UUID, filename: str) -> FileResponse:
        content = await ResolveBundleFile(store, artifact_root=artifact_root)(bundle_id, filename)
        return FileResponse(
            content.path,
            media_type=content.media_type,
            filename=content.filename,
            content_disposition_type="attachment",
            headers={"Cache-Control": "private, no-store"},
        )

    return router
