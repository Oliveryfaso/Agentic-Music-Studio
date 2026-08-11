"""FastAPI application factory and the first transactional HTTP slice."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from motif_forge import __version__
from motif_forge.application.errors import ApplicationError, RevisionConflictError
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.config import Settings, get_settings
from motif_forge.domain.commands import EDITOR_COMMAND_ADAPTER, EditorCommand
from motif_forge.domain.errors import DomainValidationError
from motif_forge.domain.revisions import AuthorKind
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)

LOCAL_ACTOR_ID = "local-user"
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=160)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["live", "ready"]
    service: str
    version: str


class ReadinessCheck(ApiModel):
    configured: bool
    connectivity: Literal["not_checked"] = "not_checked"


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


class SuccessEnvelope(ApiModel):
    request_id: UUID
    status: Literal["succeeded"] = "succeeded"
    data: CreateProjectData | CommandBatchData
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
    if error.code in {"BRANCH_NOT_FOUND", "REVISION_NOT_FOUND"}:
        return 404
    if error.code in {
        "REVISION_CONFLICT",
        "IDEMPOTENCY_KEY_REUSED",
        "CHANGE_IMPACT_ESCALATED",
    }:
        return 409
    if error.code == "COMMAND_ACTOR_INVALID":
        return 422
    if error.code == "PERSISTENCE_NOT_CONFIGURED":
        return 503
    return 500


def create_app(
    settings: Settings | None = None,
    *,
    uow_factory: UnitOfWorkFactory | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    engine = None
    runtime_uow = uow_factory
    if runtime_uow is None and runtime_settings.postgres_dsn is not None:
        dsn = runtime_settings.postgres_dsn.get_secret_value()
        engine = create_postgres_engine(dsn)
        runtime_uow = PostgresUnitOfWork(create_session_factory(engine))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="Motif Forge API", version=__version__, lifespan=lifespan)
    app.state.uow_factory = runtime_uow

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

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def live() -> HealthResponse:
        return HealthResponse(status="live", service="motif-forge-api", version=__version__)

    @app.get("/health/ready", response_model=ReadinessResponse, tags=["health"])
    async def ready() -> ReadinessResponse:
        return ReadinessResponse(
            status="ready",
            service="motif-forge-api",
            version=__version__,
            checks={
                "postgres": ReadinessCheck(configured=runtime_settings.postgres_dsn is not None),
                "redis": ReadinessCheck(configured=runtime_settings.redis_url is not None),
            },
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

    return app


app = create_app()
