"""Transactional L0/L1 command-batch commits."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import (
    ApplicationError,
    ChangeImpactEscalatedError,
    IdempotencyKeyReusedError,
    RevisionConflictError,
)
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import EditorCommand, apply_commands
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.policies import compute_change_impact
from motif_forge.domain.revisions import AuthorKind, ChangeImpact, Revision, VersionRefs

COMMIT_COMMAND_BATCH_OPERATION = "revision.commit-command-batch.v1"


class CommitCommandBatchRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    commands: tuple[EditorCommand, ...] = Field(min_length=1)
    actor_id: str = Field(min_length=1, max_length=160)
    author_kind: AuthorKind
    reason: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=160)
    client_sequence: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_actor_and_order(self) -> CommitCommandBatchRequest:
        expected_actor = self.author_kind.value
        if any(command.actor_kind != expected_actor for command in self.commands):
            raise ValueError("every command actor_kind must match author_kind")
        sequences = tuple(command.client_sequence for command in self.commands)
        if sequences != tuple(sorted(sequences)):
            raise ValueError("commands must be ordered by client_sequence")
        return self


class CommitCommandBatchResult(DomainModel):
    project_id: UUID
    branch_id: UUID
    revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_change_impact: ChangeImpact
    replayed: bool = False


class CommitCommandBatch:
    """Lock a Branch, apply pure commands, append a Revision, then advance its head."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        versions: VersionRefs | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock
        self._versions = versions or VersionRefs()

    async def __call__(self, request: CommitCommandBatchRequest) -> CommitCommandBatchResult:
        fingerprint = request_hash(
            {
                "schema": COMMIT_COMMAND_BATCH_OPERATION,
                "project_id": str(request.project_id),
                "branch_id": str(request.branch_id),
                "base_revision_id": str(request.base_revision_id),
                "commands": [command.model_dump(mode="json") for command in request.commands],
                "actor_id": request.actor_id,
                "author_kind": request.author_kind.value,
                "reason": request.reason,
                "client_sequence": request.client_sequence,
            }
        )
        async with self._uow_factory() as transaction:
            hit = await transaction.get_idempotency(
                operation=COMMIT_COMMAND_BATCH_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                try:
                    return CommitCommandBatchResult.model_validate_json(
                        json.dumps({**hit.result_payload, "replayed": True})
                    )
                except ValueError as exc:
                    raise ApplicationError(
                        "PERSISTENCE_INVARIANT_VIOLATION",
                        "idempotency record contains an invalid revision result",
                    ) from exc

            branch = await transaction.lock_branch(
                project_id=request.project_id, branch_id=request.branch_id
            )
            if branch is None:
                raise ApplicationError("BRANCH_NOT_FOUND", "target branch does not exist")
            if branch.head_revision_id != request.base_revision_id:
                raise RevisionConflictError(branch.head_revision_id)

            base_revision = await transaction.get_revision(request.base_revision_id)
            if base_revision is None or base_revision.project_id != request.project_id:
                raise ApplicationError("REVISION_NOT_FOUND", "base revision does not exist")

            candidate_ir = apply_commands(base_revision.arrangement_ir, request.commands)
            actual_impact = compute_change_impact(request.commands)
            if actual_impact >= ChangeImpact.L2:
                raise ChangeImpactEscalatedError

            batch_id = self._id_factory()
            revision = Revision(
                revision_id=self._id_factory(),
                project_id=request.project_id,
                parent_revision_id=base_revision.revision_id,
                created_on_branch_id=request.branch_id,
                arrangement_ir=candidate_ir,
                content_hash=arrangement_content_hash(candidate_ir),
                command_batch_id=batch_id,
                change_impact_predicted=actual_impact,
                change_impact_actual=actual_impact,
                author_kind=request.author_kind,
                created_by=request.actor_id,
                reason_code=request.reason,
                versions=self._versions,
                created_at=self._clock(),
            )
            await transaction.insert_revision(
                revision=revision,
                commands=request.commands,
                idempotency_key=request.idempotency_key,
            )
            advanced = await transaction.advance_branch_head(
                branch_id=request.branch_id,
                expected_head_id=request.base_revision_id,
                new_head_id=revision.revision_id,
            )
            if not advanced:
                raise RevisionConflictError(request.base_revision_id)
            await transaction.insert_audit_event(
                event_id=self._id_factory(),
                project_id=request.project_id,
                actor_id=request.actor_id,
                event_type="project.revision.committed",
                resource_id=revision.revision_id,
                payload={
                    "branch_id": str(request.branch_id),
                    "base_revision_id": str(request.base_revision_id),
                    "command_batch_id": str(batch_id),
                    "actual_change_impact": actual_impact.name,
                },
            )
            result = _commit_result(revision, replayed=False)
            await transaction.save_idempotency(
                operation=COMMIT_COMMAND_BATCH_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
                resource_id=revision.revision_id,
                result_payload=result.model_dump(mode="json", exclude={"replayed"}),
            )
            return result


def _commit_result(revision: Revision, *, replayed: bool) -> CommitCommandBatchResult:
    return CommitCommandBatchResult(
        project_id=revision.project_id,
        branch_id=revision.created_on_branch_id,
        revision_id=revision.revision_id,
        content_hash=revision.content_hash,
        actual_change_impact=revision.change_impact_actual,
        replayed=replayed,
    )
