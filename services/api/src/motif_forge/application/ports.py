"""Persistence ports owned by the application layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from motif_forge.domain.commands import EditorCommand
from motif_forge.domain.revisions import ProjectBranch, ProjectRootState, Revision


@dataclass(frozen=True, slots=True)
class IdempotencyHit:
    resource_id: UUID
    request_hash: str
    result_payload: dict[str, object]


class ProjectTransaction(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def get_idempotency(
        self, *, operation: str, key: str, request_hash: str
    ) -> IdempotencyHit | None: ...

    async def save_idempotency(
        self,
        *,
        operation: str,
        key: str,
        request_hash: str,
        resource_id: UUID,
        result_payload: dict[str, object],
    ) -> None: ...

    async def get_project_root(self, project_id: UUID) -> ProjectRootState | None: ...

    async def insert_project_root(self, *, name: str, root: ProjectRootState) -> None: ...

    async def lock_branch(self, *, project_id: UUID, branch_id: UUID) -> ProjectBranch | None: ...

    async def get_revision(self, revision_id: UUID) -> Revision | None: ...

    async def insert_revision(
        self,
        *,
        revision: Revision,
        commands: tuple[EditorCommand, ...],
        idempotency_key: str,
    ) -> None: ...

    async def advance_branch_head(
        self, *, branch_id: UUID, expected_head_id: UUID, new_head_id: UUID
    ) -> bool: ...

    async def insert_audit_event(
        self,
        *,
        event_id: UUID,
        project_id: UUID,
        actor_id: str,
        event_type: str,
        resource_id: UUID,
        payload: dict[str, object],
    ) -> None: ...


UnitOfWorkFactory = Callable[[], ProjectTransaction]
