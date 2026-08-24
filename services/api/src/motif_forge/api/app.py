"""FastAPI application factory and the first transactional HTTP slice."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import text
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from motif_forge import __version__
from motif_forge.agent.parent_graph import (
    build_parent_graph,
    initial_artifact_rehydrate_state,
    initial_import_state,
)
from motif_forge.api.ai_runs import build_ai_run_router
from motif_forge.api.project_reads import build_project_read_router
from motif_forge.api.sound_catalog import build_sound_catalog_router
from motif_forge.application.audio_content import ResolveAudioContent
from motif_forge.application.errors import ApplicationError, RevisionConflictError
from motif_forge.application.features import ListAudioFeatures, ReadFeatureArtifact
from motif_forge.application.imports import LoadImportAnalysisContext, MaterializeImport
from motif_forge.application.media_jobs import (
    EnqueueFollowupMediaJob,
    EnqueueMediaJob,
    LoadArtifactRehydration,
    StartArtifactRehydration,
)
from motif_forge.application.ports import (
    AIRunUnitOfWorkFactory,
    UnitOfWorkFactory,
    UploadUnitOfWorkFactory,
)
from motif_forge.application.project_reads import ProjectReadStore
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.application.storage import (
    LocalArtifactCollector,
    LocalStorageRootInspector,
    PersistentStorageEventRecorder,
    PostgresStorageFactsLoader,
    RunStoragePressureGate,
    StorageRootSnapshot,
)
from motif_forge.application.undo import UndoCommittedRevision, UndoCommittedRevisionRequest
from motif_forge.application.uploads import (
    CompleteUpload,
    CompleteUploadResult,
    CreateUploadSession,
    CreateUploadSessionRequest,
    PutUploadPart,
)
from motif_forge.audio.uploads import LocalUploadWorkspace
from motif_forge.config import Settings, get_settings
from motif_forge.domain.commands import EDITOR_COMMAND_ADAPTER, EditorCommand
from motif_forge.domain.errors import DomainValidationError
from motif_forge.domain.media_jobs import ArtifactValidationStatus
from motif_forge.domain.revisions import AuthorKind
from motif_forge.domain.uploads import DeclaredAudioFormat, RightsDeclaration
from motif_forge.infrastructure.checkpoints import postgres_checkpointer
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.project_reads import PostgresProjectReadStore
from motif_forge.infrastructure.persistence.storage import PostgresStorageUnitOfWork
from motif_forge.infrastructure.persistence.uploads import PostgresUploadUnitOfWork

LOCAL_ACTOR_ID = "local-user"
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=160)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["live", "ready", "not_ready"]
    service: str
    version: str


class ReadinessCheck(ApiModel):
    configured: bool
    connectivity: Literal["connected", "failed", "not_configured"]


class ReadinessResponse(HealthResponse):
    checks: dict[str, ReadinessCheck]


class CreateProjectBody(ApiModel):
    name: str = Field(min_length=1, max_length=120)


class CreateProjectData(ApiModel):
    project_id: UUID
    active_branch_id: UUID
    root_revision_id: UUID
    content_hash: str
    replayed: bool


class CommandBatchBody(ApiModel):
    branch_id: UUID
    base_revision_id: UUID
    commands: tuple[EditorCommand, ...] = Field(min_length=1)
    client_sequence: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=100)

    @field_validator("commands", mode="before")
    @classmethod
    def parse_domain_commands(cls, value: object) -> tuple[EditorCommand, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("commands must be an array")
        return tuple(
            EDITOR_COMMAND_ADAPTER.validate_python(command, strict=False) for command in value
        )


class CommandBatchData(ApiModel):
    branch_id: UUID
    revision_id: UUID
    content_hash: str
    actual_change_impact: Literal["L0", "L1", "L2", "L3"]
    render_state: Literal["dirty"] = "dirty"
    replayed: bool


class UndoRevisionBody(ApiModel):
    branch_id: UUID
    base_revision_id: UUID
    target_revision_id: UUID


class UndoRevisionData(CommandBatchData):
    undone_revision_id: UUID


class CreateUploadBody(ApiModel):
    project_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)
    declared_format: DeclaredAudioFormat
    rights_declaration: RightsDeclaration
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class UploadSessionData(ApiModel):
    upload_id: UUID
    project_id: UUID
    part_size_bytes: int
    next_part_number: int
    expires_at: str


class UploadPartData(ApiModel):
    upload_id: UUID
    accepted_part_number: int
    received_bytes: int
    next_part_number: int
    replayed: bool


class CompleteUploadData(ApiModel):
    upload_id: UUID
    source_artifact_id: UUID
    content_hash: str
    byte_size: int
    detected_format: DeclaredAudioFormat
    validation_status: ArtifactValidationStatus
    replayed: bool


class StartImportBody(ApiModel):
    branch_id: UUID
    base_revision_id: UUID
    source_artifact_id: UUID


class ImportRunData(ApiModel):
    thread_id: str
    run_id: UUID
    job_id: UUID | None = None
    phase: Literal["waiting_worker", "analysis_confirmation_required", "completed", "failed"]
    artifact_id: UUID | None = None
    source_artifact_id: UUID | None = None
    normalized_artifact_id: UUID | None = None
    revision_id: UUID | None = None
    error_code: str | None = None
    replayed: bool = False
    analysis: dict[str, Any] | None = None


class RehydrateRunData(ApiModel):
    thread_id: str
    run_id: UUID
    job_id: UUID | None = None
    artifact_id: UUID
    phase: Literal["waiting_worker", "completed", "failed"]
    error_code: str | None = None
    replayed: bool = False


class FeatureArtifactData(ApiModel):
    artifact_id: UUID
    project_id: UUID
    source_audio_artifact_id: UUID
    feature_profile: str
    feature_schema_version: str
    availability: Literal["available", "evicted", "missing", "rehydrating"]
    content_hash: str
    byte_size: int
    payload: dict[str, Any] | None = None


class AudioFeatureSetData(ApiModel):
    source_audio_artifact_id: UUID
    features: tuple[FeatureArtifactData, ...]


class ConfirmImportAnalysisBody(ApiModel):
    action: Literal["confirm", "override", "skip_alignment", "cancel"]
    source_bpm: float | None = Field(default=None, ge=30.0, le=300.0)
    key_tonic: Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] | None = (
        None
    )
    key_mode: Literal["major", "minor"] | None = None


class SuccessEnvelope(ApiModel):
    request_id: UUID
    status: Literal["succeeded"] = "succeeded"
    data: (
        CreateProjectData
        | UndoRevisionData
        | CommandBatchData
        | UploadSessionData
        | UploadPartData
        | CompleteUploadData
        | ImportRunData
        | RehydrateRunData
        | FeatureArtifactData
        | AudioFeatureSetData
    )
    warnings: tuple[str, ...] = ()
    trace_id: UUID


def _request_identity(request: Request) -> tuple[UUID, UUID]:
    return request.state.request_id, request.state.trace_id


def _problem(
    request: Request,
    *,
    status: int,
    title: str,
    detail: str,
    error_code: str,
    retryable: bool,
    **extensions: Any,
) -> JSONResponse:
    _, trace_id = _request_identity(request)
    payload: dict[str, Any] = {
        "type": f"urn:motif-forge:error:{error_code.lower().replace('_', '-')}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "error_code": error_code,
        "retryable": retryable,
        "trace_id": str(trace_id),
    }
    payload.update(extensions)
    return JSONResponse(payload, status_code=status, media_type="application/problem+json")


def _application_status(error: ApplicationError) -> int:
    if error.code in {
        "BRANCH_NOT_FOUND",
        "REVISION_NOT_FOUND",
        "PROJECT_NOT_FOUND",
        "UPLOAD_NOT_FOUND",
        "ARTIFACT_NOT_FOUND",
        "IMPORT_RUN_NOT_FOUND",
    }:
        return 404
    if error.code in {
        "REVISION_CONFLICT",
        "IDEMPOTENCY_KEY_REUSED",
        "CHANGE_IMPACT_ESCALATED",
        "UPLOAD_STATE_CONFLICT",
        "UPLOAD_PART_OUT_OF_ORDER",
        "IMPORT_CONFIRMATION_STATE_CONFLICT",
        "ARTIFACT_ALREADY_AVAILABLE",
        "ARTIFACT_REHYDRATING",
        "ARTIFACT_REHYDRATION_STATE_CONFLICT",
        "ARTIFACT_REHYDRATION_DEPENDENCY_UNAVAILABLE",
        "ARTIFACT_EVICTED",
        "AI_RUN_BASE_REVISION_CONFLICT",
        "AI_RUN_REPLAN_STATE_CONFLICT",
    }:
        return 409
    if error.code in {
        "COMMAND_ACTOR_INVALID",
        "UPLOAD_TOO_LARGE",
        "UPLOAD_EXPIRED",
        "UPLOAD_INCOMPLETE",
        "UPLOAD_CHECKSUM_MISMATCH",
        "UPLOAD_FORMAT_MISMATCH",
        "UPLOAD_MEDIA_TYPE_UNSUPPORTED",
        "UPLOAD_PART_TOO_LARGE",
        "UPLOAD_PART_EMPTY",
        "UPLOAD_SIZE_MISMATCH",
        "UPLOAD_PART_MISSING",
        "IMPORT_THREAD_INVALID",
        "ARTIFACT_REHYDRATION_UNSUPPORTED",
        "ARTIFACT_REHYDRATION_RECIPE_INVALID",
        "ARTIFACT_NOT_PLAYABLE",
        "PLAN_ADJUSTMENT_TOO_LARGE",
    }:
        return 422
    if error.code in {"PERSISTENCE_NOT_CONFIGURED", "ARTIFACT_ROOT_UNAVAILABLE"}:
        return 503
    if error.code == "STORAGE_QUOTA_EXCEEDED":
        return 507
    if error.code == "ARTIFACT_MISSING":
        return 410
    return 500


def create_app(
    settings: Settings | None = None,
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    upload_uow_factory: UploadUnitOfWorkFactory | None = None,
    ai_run_uow_factory: AIRunUnitOfWorkFactory | None = None,
    project_read_store: ProjectReadStore | None = None,
    storage_root_inspector: Callable[[], StorageRootSnapshot] | None = None,
    readiness_probes: Mapping[str, Callable[[], Awaitable[bool]]] | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    engine = None
    redis_client: Redis | None = None
    runtime_uow = uow_factory
    runtime_upload_uow = upload_uow_factory
    runtime_ai_run_uow = ai_run_uow_factory
    runtime_project_reads = project_read_store
    runtime_media_uow = None
    runtime_storage_gate = None
    if runtime_uow is None and runtime_settings.postgres_dsn is not None:
        dsn = runtime_settings.postgres_dsn.get_secret_value()
        engine = create_postgres_engine(dsn)
        session_factory = create_session_factory(engine)
        runtime_uow = PostgresUnitOfWork(session_factory)
        runtime_upload_uow = PostgresUploadUnitOfWork(session_factory)
        runtime_ai_run_uow = PostgresAIRunUnitOfWork(session_factory)
        runtime_project_reads = PostgresProjectReadStore(session_factory)
        runtime_media_uow = PostgresMediaJobUnitOfWork(session_factory)
        storage_uow = PostgresStorageUnitOfWork(session_factory)
        runtime_storage_gate = RunStoragePressureGate(
            inspect_root=LocalStorageRootInspector(runtime_settings.artifact_root),
            load_facts=PostgresStorageFactsLoader(
                storage_uow, temp_root=runtime_settings.temp_root
            ),
            collector=LocalArtifactCollector(
                storage_uow, artifact_root=runtime_settings.artifact_root
            ),
            record_event=PersistentStorageEventRecorder(storage_uow),
            global_quota_bytes=runtime_settings.artifact_global_quota_bytes,
            project_quota_bytes=runtime_settings.artifact_project_quota_bytes,
            temp_quota_bytes=runtime_settings.temp_quota_bytes,
            minimum_free_bytes=runtime_settings.storage_min_free_bytes,
        )
    if runtime_settings.redis_url is not None:
        redis_client = Redis.from_url(
            runtime_settings.redis_url.get_secret_value(),
            decode_responses=True,
        )

    async def probe_postgres() -> bool:
        if engine is None:
            return False
        async with engine.connect() as connection:
            value = cast(int, (await connection.execute(text("SELECT 1"))).scalar_one())
            return value == 1

    async def probe_redis() -> bool:
        if redis_client is None:
            return False
        return bool(await redis_client.ping())

    async def probe_artifact_root() -> bool:
        snapshot = LocalStorageRootInspector(runtime_settings.artifact_root)()
        return snapshot.health.value == "ready" and snapshot.identity_matches

    runtime_probes = dict(readiness_probes or {})
    runtime_probes.setdefault("postgres", probe_postgres)
    runtime_probes.setdefault("redis", probe_redis)
    runtime_probes.setdefault("artifact_root", probe_artifact_root)

    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI) -> AsyncIterator[None]:
        checkpointer_context = None
        if runtime_media_uow is not None and runtime_settings.postgres_dsn is not None:
            checkpointer_context = postgres_checkpointer(
                runtime_settings.postgres_dsn.get_secret_value()
            )
            saver = await checkpointer_context.__aenter__()
            project_uow = cast(UnitOfWorkFactory, runtime_uow)
            lifespan_app.state.parent_graph = build_parent_graph(
                EnqueueMediaJob(runtime_media_uow),
                checkpointer=saver,
                materialize_import=MaterializeImport(project_uow, runtime_media_uow),
                load_import_context=LoadImportAnalysisContext(project_uow, runtime_media_uow),
                enqueue_followup_media_job=EnqueueFollowupMediaJob(runtime_media_uow),
                enqueue_artifact_rehydration=StartArtifactRehydration(runtime_media_uow),
                load_artifact_rehydration=LoadArtifactRehydration(runtime_media_uow),
                storage_pressure_gate=runtime_storage_gate,
            )
        try:
            yield
        finally:
            if checkpointer_context is not None:
                await checkpointer_context.__aexit__(None, None, None)
            if engine is not None:
                await engine.dispose()
            if redis_client is not None:
                await redis_client.aclose()

    app = FastAPI(title="Motif Forge API", version=__version__, lifespan=lifespan)
    app.state.uow_factory = runtime_uow
    app.state.upload_uow_factory = runtime_upload_uow
    app.state.upload_workspace = LocalUploadWorkspace(runtime_settings.artifact_root)
    app.state.parent_graph = None
    app.include_router(build_sound_catalog_router())
    if runtime_ai_run_uow is not None:
        app.include_router(
            build_ai_run_router(runtime_ai_run_uow, project_uow=runtime_uow)
        )
    if runtime_project_reads is not None:
        app.include_router(
            build_project_read_router(
                runtime_project_reads,
                storage_root_inspector
                or LocalStorageRootInspector(runtime_settings.artifact_root),
            )
        )

    @app.middleware("http")
    async def add_request_identity(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.request_id = uuid4()
        request.state.trace_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["X-Trace-ID"] = str(request.state.trace_id)
        return response

    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, error: ApplicationError) -> JSONResponse:
        extensions: dict[str, Any] = {}
        if isinstance(error, RevisionConflictError):
            extensions["current_revision_id"] = str(error.current_revision_id)
        return _problem(
            request,
            status=_application_status(error),
            title=error.code.replace("_", " ").title(),
            detail=error.message,
            error_code=error.code,
            retryable=error.retryable,
            **extensions,
        )

    @app.exception_handler(DomainValidationError)
    async def handle_domain_error(request: Request, error: DomainValidationError) -> JSONResponse:
        return _problem(
            request,
            status=422,
            title="Domain Validation Failed",
            detail="one or more editor commands violate domain constraints",
            error_code="DOMAIN_VALIDATION_FAILED",
            retryable=False,
            validation_issues=[issue.model_dump(mode="json") for issue in error.issues],
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_error(request: Request, error: RequestValidationError) -> JSONResponse:
        issues = [
            {
                "code": item["type"],
                "path": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
            }
            for item in error.errors()
        ]
        return _problem(
            request,
            status=422,
            title="Request Validation Failed",
            detail="the request does not match the API schema",
            error_code="REQUEST_VALIDATION_FAILED",
            retryable=False,
            validation_issues=issues,
        )

    def require_uow() -> UnitOfWorkFactory:
        configured = cast(UnitOfWorkFactory | None, app.state.uow_factory)
        if configured is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED",
                "project writes require MOTIF_FORGE_POSTGRES_DSN",
                retryable=False,
            )
        return configured

    def require_upload_uow() -> UploadUnitOfWorkFactory:
        configured = cast(UploadUnitOfWorkFactory | None, app.state.upload_uow_factory)
        if configured is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED",
                "uploads require MOTIF_FORGE_POSTGRES_DSN",
                retryable=False,
            )
        return configured

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def live() -> HealthResponse:
        return HealthResponse(status="live", service="motif-forge-api", version=__version__)

    @app.get("/health/ready", response_model=ReadinessResponse, tags=["health"])
    async def ready(response: Response) -> ReadinessResponse:
        configured = {
            "postgres": runtime_settings.postgres_dsn is not None,
            "redis": runtime_settings.redis_url is not None,
            "artifact_root": True,
        }
        checks: dict[str, ReadinessCheck] = {}
        for name in ("postgres", "redis", "artifact_root"):
            if not configured[name]:
                checks[name] = ReadinessCheck(configured=False, connectivity="not_configured")
                continue
            try:
                connected = await asyncio.wait_for(
                    runtime_probes[name](),
                    timeout=runtime_settings.readiness_timeout_seconds,
                )
            except Exception:
                connected = False
            checks[name] = ReadinessCheck(
                configured=True,
                connectivity="connected" if connected else "failed",
            )
        is_ready = all(check.connectivity == "connected" for check in checks.values())
        if not is_ready:
            response.status_code = 503
        return ReadinessResponse(
            status="ready" if is_ready else "not_ready",
            service="motif-forge-api",
            version=__version__,
            checks=checks,
        )

    @app.post("/api/v1/projects", response_model=SuccessEnvelope, status_code=201)
    async def create_project(
        body: CreateProjectBody,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> SuccessEnvelope:
        request_id, trace_id = _request_identity(request)
        result = await CreateProject(require_uow())(
            CreateProjectRequest(
                name=body.name,
                actor_id=LOCAL_ACTOR_ID,
                idempotency_key=idempotency_key,
            )
        )
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=CreateProjectData.model_validate(result.model_dump()),
        )

    @app.post(
        "/api/v1/projects/{project_id}/command-batches",
        response_model=SuccessEnvelope,
        status_code=201,
    )
    async def commit_command_batch(
        project_id: UUID,
        body: CommandBatchBody,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> SuccessEnvelope:
        if any(command.actor_kind != AuthorKind.HUMAN.value for command in body.commands):
            raise ApplicationError(
                "COMMAND_ACTOR_INVALID",
                "the public command-batch endpoint only accepts human editor commands",
            )
        request_id, trace_id = _request_identity(request)
        result = await CommitCommandBatch(require_uow())(
            CommitCommandBatchRequest(
                project_id=project_id,
                branch_id=body.branch_id,
                base_revision_id=body.base_revision_id,
                commands=body.commands,
                actor_id=LOCAL_ACTOR_ID,
                author_kind=AuthorKind.HUMAN,
                reason=body.reason,
                idempotency_key=idempotency_key,
                client_sequence=body.client_sequence,
            )
        )
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=CommandBatchData(
                branch_id=result.branch_id,
                revision_id=result.revision_id,
                content_hash=result.content_hash,
                actual_change_impact=result.actual_change_impact.name,
                replayed=result.replayed,
            ),
        )

    @app.post(
        "/api/v1/projects/{project_id}/undo",
        response_model=SuccessEnvelope,
        status_code=201,
    )
    async def undo_committed_revision(
        project_id: UUID,
        body: UndoRevisionBody,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> SuccessEnvelope:
        request_id, trace_id = _request_identity(request)
        result = await UndoCommittedRevision(require_uow())(
            UndoCommittedRevisionRequest(
                project_id=project_id,
                branch_id=body.branch_id,
                base_revision_id=body.base_revision_id,
                target_revision_id=body.target_revision_id,
                actor_id=LOCAL_ACTOR_ID,
                idempotency_key=idempotency_key,
            )
        )
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=UndoRevisionData(
                branch_id=result.branch_id,
                revision_id=result.revision_id,
                undone_revision_id=result.undone_revision_id,
                content_hash=result.content_hash,
                actual_change_impact=result.actual_change_impact.name,
                replayed=result.replayed,
            ),
        )

    @app.post("/api/v1/upload-sessions", response_model=SuccessEnvelope, status_code=201)
    async def create_upload_session(
        body: CreateUploadBody, request: Request, idempotency_key: IdempotencyKey
    ) -> SuccessEnvelope:
        request_id, trace_id = _request_identity(request)
        result = await CreateUploadSession(
            require_upload_uow(),
            max_upload_bytes=runtime_settings.upload_max_bytes,
            part_size_bytes=runtime_settings.upload_part_size_bytes,
            ttl_hours=runtime_settings.upload_session_ttl_hours,
            artifact_root=runtime_settings.artifact_root,
            min_free_bytes=runtime_settings.storage_min_free_bytes,
            storage_pressure_gate=runtime_storage_gate,
        )(
            CreateUploadSessionRequest(
                project_id=body.project_id,
                original_filename=body.filename,
                declared_format=body.declared_format,
                rights_declaration=body.rights_declaration,
                expected_sha256=body.expected_sha256,
                byte_size=body.byte_size,
                idempotency_key=idempotency_key,
            )
        )
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=UploadSessionData(
                upload_id=result.upload_id,
                project_id=result.project_id,
                part_size_bytes=result.part_size_bytes,
                next_part_number=result.next_part_number,
                expires_at=result.expires_at.isoformat(),
            ),
        )

    @app.put(
        "/api/v1/upload-sessions/{upload_id}/parts/{part_number}",
        response_model=SuccessEnvelope,
    )
    async def put_upload_part(
        upload_id: UUID, part_number: int, request: Request
    ) -> SuccessEnvelope:
        request_id, trace_id = _request_identity(request)
        result = await PutUploadPart(
            require_upload_uow(), cast(LocalUploadWorkspace, app.state.upload_workspace)
        )(
            upload_id=upload_id,
            part_number=part_number,
            body=request.stream(),
        )
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=UploadPartData.model_validate(result.model_dump()),
        )

    @app.post(
        "/api/v1/upload-sessions/{upload_id}/complete",
        response_model=SuccessEnvelope,
    )
    async def complete_upload(upload_id: UUID, request: Request) -> SuccessEnvelope:
        request_id, trace_id = _request_identity(request)
        result: CompleteUploadResult = await CompleteUpload(
            require_upload_uow(), cast(LocalUploadWorkspace, app.state.upload_workspace)
        )(upload_id)
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=CompleteUploadData.model_validate(result.model_dump()),
        )

    @app.post(
        "/api/v1/artifacts/{artifact_id}/rehydrate",
        response_model=SuccessEnvelope,
        status_code=202,
    )
    async def rehydrate_artifact(
        artifact_id: UUID,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> SuccessEnvelope:
        graph = app.state.parent_graph
        if graph is None or runtime_media_uow is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED",
                "Artifact rehydration requires PostgreSQL-backed Parent Graph checkpoints",
            )
        fingerprint = sha256(f"{artifact_id}:{idempotency_key}".encode()).hexdigest()
        thread_id = f"rehydrate-{fingerprint[:32]}"
        state = initial_artifact_rehydrate_state(
            thread_id=thread_id,
            artifact_id=artifact_id,
            idempotency_key=idempotency_key,
        )
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        existing = snapshot.values
        replayed = bool(existing)
        result = existing if replayed else await graph.ainvoke(state, config)
        if replayed and (
            existing.get("request_payload", {}).get("target_artifact_id") != str(artifact_id)
        ):
            raise ApplicationError(
                "IDEMPOTENCY_KEY_REUSED",
                "the idempotency key was used with a different rehydration request",
            )
        if result.get("phase") not in {"waiting_worker", "completed", "failed"}:
            raise ApplicationError(
                result.get("error_code", "ARTIFACT_REHYDRATION_START_FAILED"),
                "the rehydration workflow did not reach a stable boundary",
            )
        if result.get("phase") == "failed" and not result.get("run_id"):
            raise ApplicationError(
                result.get("error_code", "ARTIFACT_REHYDRATION_START_FAILED"),
                "the Artifact could not enter a durable rehydration Run",
            )
        request_id, trace_id = _request_identity(request)
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=RehydrateRunData(
                thread_id=thread_id,
                run_id=UUID(result["run_id"]),
                job_id=(UUID(result["pending_job_id"]) if result.get("pending_job_id") else None),
                artifact_id=artifact_id,
                phase=cast(Literal["waiting_worker", "completed", "failed"], result["phase"]),
                error_code=result.get("error_code"),
                replayed=replayed,
            ),
        )

    @app.get(
        "/api/v1/feature-artifacts/{artifact_id}",
        response_model=SuccessEnvelope,
    )
    async def read_feature_artifact(artifact_id: UUID, request: Request) -> SuccessEnvelope:
        if runtime_media_uow is None:
            raise ApplicationError("PERSISTENCE_NOT_CONFIGURED", "Feature reads require PostgreSQL")
        result = await ReadFeatureArtifact(
            runtime_media_uow, artifact_root=runtime_settings.artifact_root
        )(artifact_id)
        request_id, trace_id = _request_identity(request)
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=FeatureArtifactData.model_validate(result.model_dump(mode="json")),
        )

    @app.get("/api/v1/audio-artifacts/{artifact_id}/content", response_class=FileResponse)
    async def read_audio_content(artifact_id: UUID) -> FileResponse:
        if runtime_media_uow is None:
            raise ApplicationError("PERSISTENCE_NOT_CONFIGURED", "Audio reads require PostgreSQL")
        content = await ResolveAudioContent(
            runtime_media_uow, artifact_root=runtime_settings.artifact_root
        )(artifact_id)
        return FileResponse(
            content.path,
            media_type=content.media_type,
            filename=content.filename,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get(
        "/api/v1/audio-artifacts/{artifact_id}/features",
        response_model=SuccessEnvelope,
    )
    async def list_audio_features(artifact_id: UUID, request: Request) -> SuccessEnvelope:
        if runtime_media_uow is None:
            raise ApplicationError("PERSISTENCE_NOT_CONFIGURED", "Feature reads require PostgreSQL")
        result = await ListAudioFeatures(runtime_media_uow)(artifact_id)
        request_id, trace_id = _request_identity(request)
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=AudioFeatureSetData.model_validate(result.model_dump(mode="json")),
        )

    @app.post(
        "/api/v1/projects/{project_id}/imports",
        response_model=SuccessEnvelope,
        status_code=202,
    )
    async def start_import(
        project_id: UUID,
        body: StartImportBody,
        request: Request,
        idempotency_key: IdempotencyKey,
    ) -> SuccessEnvelope:
        graph = app.state.parent_graph
        if graph is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED",
                "imports require PostgreSQL-backed Parent Graph checkpoints",
            )
        fingerprint = sha256(f"{project_id}:{idempotency_key}".encode()).hexdigest()
        thread_id = f"import-{fingerprint[:32]}"
        state = initial_import_state(
            thread_id=thread_id,
            project_id=project_id,
            branch_id=body.branch_id,
            base_revision_id=body.base_revision_id,
            source_artifact_id=body.source_artifact_id,
            idempotency_key=idempotency_key,
        )
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        existing = snapshot.values
        replayed = bool(existing)
        if replayed:
            identity_fields = (
                ("project_id", state["project_id"]),
                ("branch_id", state["branch_id"]),
                ("base_revision_id", state["base_revision_id"]),
                ("request_payload", state["request_payload"]),
            )
            if any(existing.get(key) != value for key, value in identity_fields):
                raise ApplicationError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "the idempotency key was used with a different import request",
                )
            result = existing
        else:
            result = await graph.ainvoke(state, config)
        if result.get("phase") not in {
            "waiting_worker",
            "analysis_confirmation_required",
            "completed",
            "failed",
        }:
            raise ApplicationError(
                result.get("error_code", "IMPORT_START_FAILED"),
                "the import workflow did not reach a stable boundary",
            )
        request_id, trace_id = _request_identity(request)
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=_import_run_data(result, thread_id=thread_id, replayed=replayed),
        )

    @app.get(
        "/api/v1/imports/{thread_id}",
        response_model=SuccessEnvelope,
    )
    async def read_import_run(thread_id: str, request: Request) -> SuccessEnvelope:
        graph = app.state.parent_graph
        if graph is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED",
                "import reads require PostgreSQL-backed Parent Graph checkpoints",
            )
        _validate_import_thread_id(thread_id)
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        state = snapshot.values
        if not state or state.get("operation") != "import_audio":
            raise ApplicationError("IMPORT_RUN_NOT_FOUND", "the Import Run does not exist")
        if state.get("phase") not in {
            "waiting_worker",
            "analysis_confirmation_required",
            "completed",
            "failed",
        }:
            raise ApplicationError(
                "IMPORT_RUN_STATE_UNAVAILABLE",
                "the Import Run has not reached a readable checkpoint boundary",
                retryable=True,
            )
        request_id, trace_id = _request_identity(request)
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=_import_run_data(state, thread_id=thread_id),
        )

    @app.post(
        "/api/v1/imports/{thread_id}/confirm-analysis",
        response_model=SuccessEnvelope,
    )
    async def confirm_import_analysis(
        thread_id: str, body: ConfirmImportAnalysisBody, request: Request
    ) -> SuccessEnvelope:
        graph = app.state.parent_graph
        if graph is None:
            raise ApplicationError(
                "PERSISTENCE_NOT_CONFIGURED",
                "import confirmation requires PostgreSQL-backed Parent Graph checkpoints",
            )
        _validate_import_thread_id(thread_id)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        if snapshot.values.get("phase") != "analysis_confirmation_required":
            raise ApplicationError(
                "IMPORT_CONFIRMATION_STATE_CONFLICT",
                "the import is not waiting for analysis confirmation",
            )
        result = await graph.ainvoke(Command(resume=body.model_dump(mode="json")), config)
        request_id, trace_id = _request_identity(request)
        return SuccessEnvelope(
            request_id=request_id,
            trace_id=trace_id,
            data=_import_run_data(result, thread_id=thread_id),
        )

    return app


def _import_analysis_projection(state: Mapping[str, Any]) -> dict[str, Any] | None:
    if "analysis_policy_version" not in state:
        return None
    return {
        "bpm": state.get("source_bpm"),
        "bpm_confidence": state.get("bpm_confidence"),
        "key_tonic": state.get("key_tonic"),
        "key_mode": state.get("key_mode"),
        "key_confidence": state.get("key_confidence"),
        "project_bpm": state.get("project_bpm"),
        "policy_version": state.get("analysis_policy_version"),
        "explanation_code": state.get("analysis_explanation_code"),
    }


def _validate_import_thread_id(thread_id: str) -> None:
    if re.fullmatch(r"import-[0-9a-f]{32}", thread_id) is None:
        raise ApplicationError("IMPORT_THREAD_INVALID", "the import thread ID is invalid")


def _import_run_data(
    state: Mapping[str, Any], *, thread_id: str, replayed: bool = False
) -> ImportRunData:
    refs = state.get("artifact_refs", [])
    request_payload = state.get("request_payload", {})
    source_artifact_id = (
        request_payload.get("source_artifact_id")
        if isinstance(request_payload, Mapping)
        else None
    )
    return ImportRunData(
        thread_id=thread_id,
        run_id=UUID(state["run_id"]),
        job_id=(UUID(state["pending_job_id"]) if state.get("pending_job_id") else None),
        phase=cast(
            Literal["waiting_worker", "analysis_confirmation_required", "completed", "failed"],
            state["phase"],
        ),
        artifact_id=UUID(refs[0]) if refs else None,
        source_artifact_id=UUID(source_artifact_id) if source_artifact_id else None,
        normalized_artifact_id=(
            UUID(state["normalized_artifact_id"])
            if state.get("normalized_artifact_id")
            else None
        ),
        revision_id=(
            UUID(state["materialized_revision_id"])
            if state.get("materialized_revision_id")
            else None
        ),
        error_code=state.get("error_code"),
        replayed=replayed,
        analysis=_import_analysis_projection(state),
    )


app = create_app()
