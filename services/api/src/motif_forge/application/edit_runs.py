"""Creation of durable finite Edit Runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, IdempotencyKeyReusedError
from motif_forge.application.ports import AIRunUnitOfWorkFactory, UnitOfWorkFactory
from motif_forge.domain.ai_runs import (
    EDIT_RUN_STATE_SCHEMA_VERSION,
    PARENT_GRAPH_TOPOLOGY_VERSION,
    AIRun,
    AIRunEvent,
    AIRunType,
    EditRunRequest,
)
from motif_forge.domain.ir import ArrangementIR, DomainModel

CREATE_EDIT_RUN_OPERATION = "ai-run.create-edit.v1"


class CreateEditAIRunRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    edit_request: EditRunRequest
    idempotency_key: str = Field(min_length=8, max_length=160)
    max_model_requests: int = Field(default=1, ge=1, le=3)
    max_total_tokens: int = Field(default=4_000, ge=1, le=12_000)


class CreateEditAIRun:
    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, request: CreateEditAIRunRequest) -> AIRun:
        fingerprint = request_hash(
            {
                "schema": CREATE_EDIT_RUN_OPERATION,
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        async with self._uow_factory() as transaction:
            hit = await transaction.get_ai_run_idempotency(
                project_id=request.project_id, key=request.idempotency_key
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return await transaction.read_ai_run(hit.resource_id)
            now = self._clock()
            run = AIRun(
                run_id=self._id_factory(),
                project_id=request.project_id,
                branch_id=request.branch_id,
                base_revision_id=request.base_revision_id,
                thread_id=request.thread_id,
                run_type=AIRunType.EDIT,
                edit_request=request.edit_request.model_dump(mode="json"),
                graph_topology_version=PARENT_GRAPH_TOPOLOGY_VERSION,
                state_schema_version=EDIT_RUN_STATE_SCHEMA_VERSION,
                idempotency_key=request.idempotency_key,
                max_model_requests=request.max_model_requests,
                max_total_tokens=request.max_total_tokens,
                created_at=now,
                updated_at=now,
            )
            await transaction.create_ai_run(
                run=run,
                created_event=AIRunEvent(
                    sequence=1,
                    event_id=self._id_factory(),
                    run_id=run.run_id,
                    event_type="ai_run.created",
                    phase="queued",
                    payload={"thread_id": run.thread_id, "run_type": "edit"},
                    dedupe_key="created",
                    created_at=now,
                ),
                outbox_event_id=self._id_factory(),
                request_hash=fingerprint,
            )
            return run


class ReadEditBase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, run: AIRun) -> ArrangementIR:
        async with self._uow_factory() as transaction:
            revision = await transaction.get_revision(run.base_revision_id)
        if revision is None or revision.project_id != run.project_id:
            raise ApplicationError(
                "EDIT_BASE_NOT_FOUND", "authoritative base Revision is unavailable"
            )
        return revision.arrangement_ir
