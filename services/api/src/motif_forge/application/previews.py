"""Transactional Candidate Snapshot, Preview, and human decision use cases."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import (
    ApplicationError,
    IdempotencyKeyReusedError,
    RevisionConflictError,
)
from motif_forge.application.ports import ProjectTransaction, UnitOfWorkFactory
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import EditorCommand, apply_commands
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.policies import compute_change_impact
from motif_forge.domain.revisions import (
    AuthorKind,
    ChangeImpact,
    PreviewCandidate,
    PreviewStatus,
    Revision,
    StructuralDiffEntry,
    VersionRefs,
    create_candidate_snapshot,
    create_preview_candidate,
    resolve_preview_candidate,
)

CREATE_COMMAND_PREVIEW_OPERATION = "preview.create-from-commands.v1"
DECIDE_PREVIEW_OPERATION = "preview.decide.v1"


class PreviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class CreateCommandPreviewRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    candidate_id: UUID
    commands: tuple[EditorCommand, ...] = Field(min_length=1)
    actor_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)
    source_run_id: UUID | None = None
    structural_diff: tuple[StructuralDiffEntry, ...] = ()

    @model_validator(mode="after")
    def require_agent_commands(self) -> CreateCommandPreviewRequest:
        if any(command.actor_kind != AuthorKind.AGENT.value for command in self.commands):
            raise ValueError("candidate preview creation only accepts agent commands")
        sequences = tuple(command.client_sequence for command in self.commands)
        if sequences != tuple(sorted(sequences)):
            raise ValueError("commands must be ordered by client_sequence")
        return self


class CreateCommandPreviewResult(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    candidate_snapshot_id: UUID
    preview_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_change_impact: ChangeImpact
    status: PreviewStatus
    replayed: bool = False


class CreateCommandPreview:
    """Persist a high-impact agent proposal without advancing the Branch head."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        preview_ttl: timedelta = timedelta(hours=24),
        versions: VersionRefs | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock
        self._preview_ttl = preview_ttl
        self._versions = versions or VersionRefs()

    async def __call__(self, request: CreateCommandPreviewRequest) -> CreateCommandPreviewResult:
        fingerprint = request_hash(
            {
                "schema": CREATE_COMMAND_PREVIEW_OPERATION,
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        async with self._uow_factory() as transaction:
            hit = await transaction.get_idempotency(
                operation=CREATE_COMMAND_PREVIEW_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return CreateCommandPreviewResult.model_validate_json(
                    json.dumps({**hit.result_payload, "replayed": True}), strict=True
                )

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
            if actual_impact < ChangeImpact.L2:
                raise ApplicationError(
                    "PREVIEW_NOT_REQUIRED", "L0/L1 changes must use the direct commit path"
                )

            now = self._clock()
            snapshot = create_candidate_snapshot(
                base_revision=base_revision,
                candidate_ir=candidate_ir,
                candidate_id=request.candidate_id,
                candidate_snapshot_id=self._id_factory(),
                source_run_id=request.source_run_id,
                structural_diff=request.structural_diff,
                versions=self._versions,
                created_at=now,
            )
            preview = create_preview_candidate(
                snapshot=snapshot,
                branch=branch,
                actual_change_impact=actual_impact,
                preview_id=self._id_factory(),
                created_at=now,
                expires_at=now + self._preview_ttl,
            )
            await transaction.insert_candidate_preview(snapshot=snapshot, preview=preview)
            result = CreateCommandPreviewResult(
                project_id=request.project_id,
                branch_id=request.branch_id,
                base_revision_id=request.base_revision_id,
                candidate_snapshot_id=snapshot.candidate_snapshot_id,
                preview_id=preview.preview_id,
                candidate_content_hash=snapshot.candidate_content_hash,
                actual_change_impact=actual_impact,
                status=preview.status,
            )
            await transaction.save_idempotency(
                operation=CREATE_COMMAND_PREVIEW_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
                resource_id=preview.preview_id,
                result_payload=result.model_dump(mode="json"),
            )
            await transaction.insert_audit_event(
                event_id=self._id_factory(),
                project_id=request.project_id,
                actor_id=request.actor_id,
                event_type="project.preview.created",
                resource_id=preview.preview_id,
                payload={
                    "candidate_snapshot_id": str(snapshot.candidate_snapshot_id),
                    "base_revision_id": str(request.base_revision_id),
                    "actual_change_impact": actual_impact.name,
                },
            )
            return result


class DecidePreviewRequest(DomainModel):
    preview_id: UUID
    decision: PreviewDecision
    actor_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)


class DecidePreviewResult(DomainModel):
    preview_id: UUID
    status: PreviewStatus
    revision_id: UUID | None = None
    replayed: bool = False


class DecidePreview:
    """Reject or atomically materialize one pending immutable candidate."""

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

    async def __call__(self, request: DecidePreviewRequest) -> DecidePreviewResult:
        fingerprint = request_hash(
            {
                "schema": DECIDE_PREVIEW_OPERATION,
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        deferred_error: ApplicationError | None = None
        result: DecidePreviewResult | None = None
        now = self._clock()

        async with self._uow_factory() as transaction:
            hit = await transaction.get_idempotency(
                operation=DECIDE_PREVIEW_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return DecidePreviewResult.model_validate_json(
                    json.dumps({**hit.result_payload, "replayed": True}), strict=True
                )

            preview = await transaction.lock_preview(request.preview_id)
            if preview is None:
                raise ApplicationError("PREVIEW_NOT_FOUND", "preview does not exist")
            if preview.status is not PreviewStatus.PENDING:
                raise ApplicationError("PREVIEW_NOT_PENDING", "preview is already terminal")

            if now >= preview.expires_at:
                resolved = resolve_preview_candidate(
                    preview,
                    status=PreviewStatus.EXPIRED,
                    decided_by="system:preview-expiry",
                    decided_at=now,
                )
                await transaction.update_preview(resolved)
                await transaction.insert_audit_event(
                    event_id=self._id_factory(),
                    project_id=preview.project_id,
                    actor_id="system:preview-expiry",
                    event_type="project.preview.expired",
                    resource_id=preview.preview_id,
                    payload={"base_revision_id": str(preview.base_revision_id)},
                )
                deferred_error = ApplicationError("PREVIEW_EXPIRED", "preview has expired")
            elif request.decision is PreviewDecision.REJECT:
                resolved = resolve_preview_candidate(
                    preview,
                    status=PreviewStatus.REJECTED,
                    decided_by=request.actor_id,
                    decided_at=now,
                )
                await transaction.update_preview(resolved)
                await transaction.insert_approval(
                    approval_id=self._id_factory(),
                    preview=resolved,
                    decision=request.decision.value,
                    actor_id=request.actor_id,
                    payload_hash=fingerprint,
                    decided_at=now,
                )
                result = DecidePreviewResult(
                    preview_id=preview.preview_id,
                    status=PreviewStatus.REJECTED,
                )
                await self._save_decision(transaction, request, fingerprint, result, resolved)
            else:
                branch = await transaction.lock_branch(
                    project_id=preview.project_id, branch_id=preview.branch_id
                )
                if branch is None:
                    raise ApplicationError("BRANCH_NOT_FOUND", "target branch does not exist")
                if branch.head_revision_id != preview.base_revision_id:
                    resolved = resolve_preview_candidate(
                        preview,
                        status=PreviewStatus.SUPERSEDED,
                        decided_by=request.actor_id,
                        decided_at=now,
                    )
                    await transaction.update_preview(resolved)
                    await transaction.insert_audit_event(
                        event_id=self._id_factory(),
                        project_id=preview.project_id,
                        actor_id=request.actor_id,
                        event_type="project.preview.superseded",
                        resource_id=preview.preview_id,
                        payload={"current_revision_id": str(branch.head_revision_id)},
                    )
                    deferred_error = RevisionConflictError(branch.head_revision_id)
                else:
                    snapshot = await transaction.get_candidate_snapshot(
                        preview.candidate_snapshot_id
                    )
                    if (
                        snapshot is None
                        or snapshot.project_id != preview.project_id
                        or snapshot.base_revision_id != preview.base_revision_id
                        or snapshot.candidate_content_hash != preview.candidate_content_hash
                        or arrangement_content_hash(snapshot.candidate_ir)
                        != preview.candidate_content_hash
                    ):
                        raise ApplicationError(
                            "CANDIDATE_INTEGRITY_ERROR",
                            "preview candidate snapshot failed identity or hash validation",
                        )
                    revision = Revision(
                        revision_id=self._id_factory(),
                        project_id=preview.project_id,
                        parent_revision_id=preview.base_revision_id,
                        created_on_branch_id=preview.branch_id,
                        arrangement_ir=snapshot.candidate_ir,
                        content_hash=snapshot.candidate_content_hash,
                        command_batch_id=self._id_factory(),
                        change_impact_predicted=preview.actual_change_impact,
                        change_impact_actual=preview.actual_change_impact,
                        author_kind=AuthorKind.HUMAN,
                        created_by=request.actor_id,
                        source_run_id=preview.source_run_id,
                        reason_code="CANDIDATE_APPROVED",
                        versions=snapshot.versions,
                        created_at=now,
                    )
                    await transaction.insert_materialized_revision(
                        revision=revision,
                        snapshot=snapshot,
                        preview=preview,
                        idempotency_key=request.idempotency_key,
                        command_id=self._id_factory(),
                    )
                    advanced = await transaction.advance_branch_head(
                        branch_id=preview.branch_id,
                        expected_head_id=preview.base_revision_id,
                        new_head_id=revision.revision_id,
                    )
                    if not advanced:
                        raise ApplicationError(
                            "PERSISTENCE_CONFLICT",
                            "branch head changed while materializing candidate",
                            retryable=True,
                        )
                    resolved = resolve_preview_candidate(
                        preview,
                        status=PreviewStatus.APPROVED,
                        decided_by=request.actor_id,
                        decided_at=now,
                        approved_revision_id=revision.revision_id,
                    )
                    await transaction.update_preview(resolved)
                    await transaction.insert_approval(
                        approval_id=self._id_factory(),
                        preview=resolved,
                        decision=request.decision.value,
                        actor_id=request.actor_id,
                        payload_hash=fingerprint,
                        decided_at=now,
                    )
                    result = DecidePreviewResult(
                        preview_id=preview.preview_id,
                        status=PreviewStatus.APPROVED,
                        revision_id=revision.revision_id,
                    )
                    await self._save_decision(transaction, request, fingerprint, result, resolved)

        if deferred_error is not None:
            raise deferred_error
        if result is None:
            raise RuntimeError("preview decision completed without result or error")
        return result

    async def _save_decision(
        self,
        transaction: ProjectTransaction,
        request: DecidePreviewRequest,
        fingerprint: str,
        result: DecidePreviewResult,
        resolved: PreviewCandidate,
    ) -> None:
        await transaction.save_idempotency(
            operation=DECIDE_PREVIEW_OPERATION,
            key=request.idempotency_key,
            request_hash=fingerprint,
            resource_id=request.preview_id,
            result_payload=result.model_dump(mode="json"),
        )
        await transaction.insert_audit_event(
            event_id=self._id_factory(),
            project_id=resolved.project_id,
            actor_id=request.actor_id,
            event_type=f"project.preview.{result.status.value}",
            resource_id=request.preview_id,
            payload={
                "revision_id": None if result.revision_id is None else str(result.revision_id)
            },
        )
        if result.revision_id is not None:
            await transaction.insert_audit_event(
                event_id=self._id_factory(),
                project_id=resolved.project_id,
                actor_id=request.actor_id,
                event_type="project.revision.committed",
                resource_id=result.revision_id,
                payload={
                    "preview_id": str(request.preview_id),
                    "base_revision_id": str(resolved.base_revision_id),
                    "actual_change_impact": resolved.actual_change_impact.name,
                },
            )
