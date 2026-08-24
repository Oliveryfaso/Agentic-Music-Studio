"""Deterministic persistence adapters for Edit Graph impact routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import AIRunUnitOfWorkFactory, UnitOfWorkFactory
from motif_forge.application.previews import (
    CreateCommandPreview,
    CreateCommandPreviewRequest,
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.revisions import CommitCommandBatch, CommitCommandBatchRequest
from motif_forge.domain.ai_runs import approval_assertion_hash
from motif_forge.domain.editing import EditPatchProposal
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.revisions import AuthorKind, PreviewCandidate


class EditPreviewDecision(DomainModel):
    action: Literal["approve", "reject", "cancel"]
    preview_id: UUID
    expected_candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: str = Field(min_length=1, max_length=160)
    approval_assertion: str = Field(min_length=16, max_length=500)
    note: str = Field(default="", max_length=500)


class AutoCommitEdit:
    def __init__(self, uow_factory: UnitOfWorkFactory, *, run_id: UUID) -> None:
        self._commit = CommitCommandBatch(uow_factory)
        self._run_id = run_id

    async def __call__(
        self, proposal: EditPatchProposal, simulation: object, state: dict[str, object]
    ) -> dict[str, object]:
        del simulation, state
        result = await self._commit(
            CommitCommandBatchRequest(
                project_id=proposal.project_id,
                branch_id=proposal.branch_id,
                base_revision_id=proposal.base_revision_id,
                commands=proposal.commands,
                actor_id="agent:edit-graph",
                author_kind=AuthorKind.AGENT,
                reason="AI_SELECTION_EDIT",
                idempotency_key=f"edit-run:{self._run_id}:commit:{proposal.proposal_id}",
            )
        )
        return {"materialized_revision_id": str(result.revision_id)}


class CreateEditPreview:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        run_id: UUID,
        ai_uow_factory: AIRunUnitOfWorkFactory | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._create = CreateCommandPreview(uow_factory)
        self._run_id = run_id
        del ai_uow_factory, clock

    async def __call__(
        self, proposal: EditPatchProposal, simulation: object, state: dict[str, object]
    ) -> dict[str, object]:
        del simulation, state
        result = await self._create(
            CreateCommandPreviewRequest(
                project_id=proposal.project_id,
                branch_id=proposal.branch_id,
                base_revision_id=proposal.base_revision_id,
                candidate_id=proposal.proposal_id,
                commands=proposal.commands,
                actor_id="agent:edit-graph",
                idempotency_key=f"edit-run:{self._run_id}:preview:{proposal.proposal_id}",
                source_run_id=self._run_id,
            )
        )
        return {
            "pending_preview_id": str(result.preview_id),
            "candidate_snapshot_id": str(result.candidate_snapshot_id),
            "candidate_content_hash": result.candidate_content_hash,
        }


class AttachEditPreviewArtifact:
    """Bind one lineage-checked rendered Artifact to an immutable edit Preview."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        run_id: UUID | None = None,
        ai_uow_factory: AIRunUnitOfWorkFactory | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._run_id = run_id
        self._ai_uow_factory = ai_uow_factory
        self._clock = clock

    async def __call__(
        self,
        *,
        preview_id: UUID,
        candidate_snapshot_id: UUID,
        expected_candidate_content_hash: str,
        preview_artifact_id: UUID,
    ) -> PreviewCandidate:
        async with self._uow_factory() as transaction:
            preview = await transaction.lock_preview(preview_id)
            snapshot = await transaction.get_candidate_snapshot(candidate_snapshot_id)
            if (
                preview is None
                or snapshot is None
                or preview.candidate_snapshot_id != candidate_snapshot_id
                or preview.candidate_content_hash != expected_candidate_content_hash
                or snapshot.candidate_content_hash != expected_candidate_content_hash
            ):
                raise ApplicationError(
                    "EDIT_PREVIEW_LINEAGE_MISMATCH",
                    "rendered evidence does not match the pending edit Preview",
                )
            if preview.preview_artifact_ids:
                if preview.preview_artifact_ids != (preview_artifact_id,):
                    raise ApplicationError(
                        "EDIT_PREVIEW_ARTIFACT_CONFLICT",
                        "the edit Preview is already bound to different evidence",
                    )
                attached = preview
            else:
                attached = preview.model_copy(
                    update={"preview_artifact_ids": (preview_artifact_id,)}
                )
                await transaction.update_preview(attached)
        if self._ai_uow_factory is not None and self._run_id is not None:
            async with self._ai_uow_factory() as transaction:
                await transaction.mark_edit_preview_pending(
                    run_id=self._run_id,
                    preview_id=preview_id,
                    now=self._clock(),
                )
        return attached


class ApplyEditPreviewDecision:
    def __init__(self, uow_factory: UnitOfWorkFactory, *, run_id: UUID) -> None:
        self._decide = DecidePreview(uow_factory)
        self._uow_factory = uow_factory
        self._run_id = run_id

    async def __call__(self, decision: EditPreviewDecision) -> dict[str, object]:
        if decision.action == "approve":
            async with self._uow_factory() as transaction:
                preview = await transaction.lock_preview(decision.preview_id)
            if preview is None or not preview.preview_artifact_ids:
                raise ApplicationError(
                    "EDIT_PREVIEW_ARTIFACT_REQUIRED",
                    "approval requires one authoritative rendered Preview artifact",
                )
        mapped = (
            PreviewDecision.APPROVE
            if decision.action == "approve"
            else PreviewDecision.REJECT
        )
        result = await self._decide(
            DecidePreviewRequest(
                preview_id=decision.preview_id,
                decision=mapped,
                actor_id=decision.actor_id,
                approval_assertion=decision.approval_assertion,
                idempotency_key=f"edit-run:{self._run_id}:decision:{decision.preview_id}",
            )
        )
        return {
            "preview_id": str(result.preview_id),
            "preview_status": result.status.value,
            "materialized_revision_id": (
                None if result.revision_id is None else str(result.revision_id)
            ),
        }


class RecordEditPreviewDecision:
    def __init__(
        self,
        uow_factory: AIRunUnitOfWorkFactory,
        *,
        project_uow_factory: UnitOfWorkFactory,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._project_uow_factory = project_uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(
        self, *, run_id: UUID, decision: EditPreviewDecision, idempotency_key: str
    ) -> EditPreviewDecision:
        assertion_hash = approval_assertion_hash(decision.approval_assertion)
        fingerprint = request_hash(
            {
                "schema": "edit-preview-decision.v1",
                "run_id": str(run_id),
                **decision.model_dump(mode="json"),
            }
        )
        async with self._uow_factory() as transaction:
            existing = await transaction.read_edit_preview_decision(run_id)
            if existing is not None:
                expected = {
                    "preview_id": decision.preview_id,
                    "action": decision.action,
                    "expected_candidate_content_hash": decision.expected_candidate_content_hash,
                    "actor_id": decision.actor_id,
                    "assertion_hash": assertion_hash,
                    "idempotency_key": idempotency_key,
                    "request_hash": fingerprint,
                    "note": decision.note,
                }
                if any(existing.get(key) != value for key, value in expected.items()):
                    raise ApplicationError(
                        "EDIT_DECISION_CONFLICT",
                        "Edit Run already has a different Preview decision",
                    )
                return decision
        async with self._project_uow_factory() as transaction:
            preview = await transaction.lock_preview(decision.preview_id)
            if (
                preview is None
                or preview.source_run_id != run_id
                or preview.candidate_content_hash
                != decision.expected_candidate_content_hash
                or not preview.preview_artifact_ids
            ):
                raise ApplicationError(
                    "EDIT_PREVIEW_NOT_READY",
                    "decision must bind the rendered Preview owned by this Edit Run",
                )
        async with self._uow_factory() as transaction:
            await transaction.record_edit_preview_decision(
                decision_id=self._id_factory(),
                run_id=run_id,
                preview_id=decision.preview_id,
                action=decision.action,
                expected_candidate_content_hash=decision.expected_candidate_content_hash,
                actor_id=decision.actor_id,
                assertion_hash=assertion_hash,
                assertion=decision.approval_assertion,
                idempotency_key=idempotency_key,
                request_hash=fingerprint,
                note=decision.note,
                outbox_event_id=self._id_factory(),
                now=self._clock(),
            )
        return decision
