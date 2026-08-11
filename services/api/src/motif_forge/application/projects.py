"""Atomic empty-project creation."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, IdempotencyKeyReusedError
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.revisions import ProjectRootState, create_root_state

CREATE_PROJECT_OPERATION = "project.create.v1"


class CreateProjectRequest(DomainModel):
    name: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)


class CreateProjectResult(DomainModel):
    project_id: UUID
    active_branch_id: UUID
    root_revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    replayed: bool = False


class CreateProject:
    """Create Project, root Revision and main Branch in one transaction."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, request: CreateProjectRequest) -> CreateProjectResult:
        fingerprint = request_hash(
            {"name": request.name, "actor_id": request.actor_id, "schema": CREATE_PROJECT_OPERATION}
        )
        async with self._uow_factory() as transaction:
            hit = await transaction.get_idempotency(
                operation=CREATE_PROJECT_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                try:
                    return CreateProjectResult.model_validate_json(
                        json.dumps({**hit.result_payload, "replayed": True})
                    )
                except ValueError as exc:
                    raise ApplicationError(
                        "PERSISTENCE_INVARIANT_VIOLATION",
                        "idempotency record contains an invalid project result",
                    ) from exc

            project_id = self._id_factory()
            root = create_root_state(
                project_id,
                created_by=request.actor_id,
                branch_id=self._id_factory(),
                revision_id=self._id_factory(),
                created_at=self._clock(),
            )
            await transaction.insert_project_root(name=request.name, root=root)
            await transaction.insert_audit_event(
                event_id=self._id_factory(),
                project_id=project_id,
                actor_id=request.actor_id,
                event_type="project.created",
                resource_id=project_id,
                payload={
                    "active_branch_id": str(root.active_branch_id),
                    "root_revision_id": str(root.revision.revision_id),
                },
            )
            result = _project_result(root, replayed=False)
            await transaction.save_idempotency(
                operation=CREATE_PROJECT_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
                resource_id=project_id,
                result_payload=result.model_dump(mode="json", exclude={"replayed"}),
            )
            return result


def _project_result(root: ProjectRootState, *, replayed: bool) -> CreateProjectResult:
    return CreateProjectResult(
        project_id=root.project_id,
        active_branch_id=root.active_branch_id,
        root_revision_id=root.revision.revision_id,
        content_hash=root.revision.content_hash,
        replayed=replayed,
    )
