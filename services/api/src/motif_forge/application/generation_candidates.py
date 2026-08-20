"""Create two immutable composition candidates and materialize only the selected one."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field

from motif_forge.agent.schemas import CompositionBrief
from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, RevisionConflictError
from motif_forge.application.generation import verify_loaded_plan_identity
from motif_forge.application.ports import CompositionMaterializationUnitOfWorkFactory
from motif_forge.application.previews import (
    DecidePreviewRequest,
    PreviewDecision,
    approve_preview_in_transaction,
)
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunApproval,
    AIRunEvent,
    AIRunStatus,
    CompositionMaterializationReceipt,
    approval_assertion_hash,
)
from motif_forge.domain.candidates import CandidateLabel
from motif_forge.domain.composition import SynthAmbientCompilationError
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.music_strategies import MusicStrategyRouter, StrategyCompilationError
from motif_forge.domain.revisions import (
    ChangeImpact,
    PreviewStatus,
    StructuralDiffEntry,
    VersionRefs,
    create_candidate_snapshot,
    create_preview_candidate,
)
from motif_forge.domain.style_packs import builtin_style_pack_registry


class CreateCompositionCandidateRequest(DomainModel):
    run_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    plan_id: UUID
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: CandidateLabel
    seed: int = Field(ge=0, le=2**31 - 1)


class CreateCompositionCandidateResult(DomainModel):
    candidate_id: UUID
    label: CandidateLabel
    seed: int
    candidate_snapshot_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    style_pack_version: str
    compiler_version: str
    replayed: bool = False


class CreateCompositionCandidate:
    """Compile a stable candidate Snapshot without creating a Revision."""

    def __init__(
        self,
        uow_factory: CompositionMaterializationUnitOfWorkFactory,
        *,
        strategy_router: MusicStrategyRouter | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._strategy_router = strategy_router or MusicStrategyRouter()
        self._clock = clock

    async def __call__(
        self, request: CreateCompositionCandidateRequest
    ) -> CreateCompositionCandidateResult:
        candidate_id = uuid5(
            NAMESPACE_URL,
            f"motif-forge:s5-candidate:{request.run_id}:{request.plan_id}:"
            f"{request.expected_plan_hash}:{request.label.value}:{request.seed}",
        )
        snapshot_id = uuid5(NAMESPACE_URL, f"motif-forge:s5-snapshot:{candidate_id}:v1")
        async with self._uow_factory() as transaction:
            run = await transaction.lock_ai_run(request.run_id)
            approval = await transaction.read_ai_run_approval(request.run_id)
            _verify_run_and_plan_approval(request, run, approval)
            persisted = await transaction.read_composition_plan(
                plan_id=request.plan_id, run_id=request.run_id
            )
            verify_loaded_plan_identity(
                persisted,
                expected_plan_hash=request.expected_plan_hash,
                require_compilation_safe=True,
            )
            existing = await transaction.get_candidate_snapshot(snapshot_id)
            if existing is not None:
                if (
                    existing.candidate_id != candidate_id
                    or existing.project_id != request.project_id
                    or existing.base_revision_id != request.base_revision_id
                    or existing.source_run_id != request.run_id
                ):
                    raise ApplicationError(
                        "CANDIDATE_IDENTITY_CONFLICT",
                        "the stable candidate identity contains different facts",
                    )
                compiler_version = existing.versions.compiler
                if compiler_version is None:
                    raise ApplicationError(
                        "CANDIDATE_IDENTITY_INVALID",
                        "candidate Snapshot is missing its compiler identity",
                    )
                return CreateCompositionCandidateResult(
                    candidate_id=candidate_id,
                    label=request.label,
                    seed=request.seed,
                    candidate_snapshot_id=existing.candidate_snapshot_id,
                    candidate_content_hash=existing.candidate_content_hash,
                    style_pack_version=persisted.style_pack_version,
                    compiler_version=compiler_version,
                    replayed=True,
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
            if run.brief is None:
                raise ApplicationError("BRIEF_NOT_FOUND", "the authoritative Brief is missing")
            try:
                brief = CompositionBrief.model_validate_json(json.dumps(run.brief), strict=True)
            except ValueError as exc:
                raise ApplicationError(
                    "BRIEF_INVALID", "the authoritative composition Brief is invalid"
                ) from exc
            expected_pack = builtin_style_pack_registry().resolve(persisted.plan.genre)
            accepted_packs = {expected_pack.pack_id}
            if persisted.plan.genre == "synth_ambient":
                accepted_packs.add("synth-ambient.v1")
            if persisted.style_pack_version not in accepted_packs:
                raise ApplicationError(
                    "PLAN_IDENTITY_MISMATCH", "the Plan or Style Pack identity is invalid"
                )
            try:
                compiled = self._strategy_router.compile(
                    request.project_id,
                    brief=brief,
                    plan=persisted.plan,
                    seed=request.seed,
                )
            except (SynthAmbientCompilationError, StrategyCompilationError) as exc:
                raise ApplicationError(
                    "PLAN_STRATEGY_INCOMPATIBLE",
                    "the approved CompositionPlan no longer satisfies the strategy policy",
                ) from exc
            snapshot = create_candidate_snapshot(
                base_revision=base_revision,
                candidate_ir=compiled.build.arrangement,
                candidate_id=candidate_id,
                commands=compiled.build.commands,
                candidate_snapshot_id=snapshot_id,
                source_run_id=request.run_id,
                structural_diff=(
                    StructuralDiffEntry(
                        operation="replace",
                        path="/arrangement",
                        summary=f"Compile candidate {request.label.value.upper()}",
                    ),
                ),
                versions=VersionRefs(
                    policy="change-impact.v1",
                    audio_engine="motif-forge-audio-engine.v1",
                    graph="motif-forge-parent.v2",
                    prompt=persisted.prompt_version,
                    knowledge=persisted.style_pack_version,
                    assets="builtin-seed-palette.v1",
                    compiler=compiled.compiler_version,
                ),
                created_at=self._clock(),
            )
            await transaction.insert_candidate_snapshot(snapshot)
            await transaction.record_ai_run_event(
                AIRunEvent(
                    sequence=1,
                    event_id=uuid4(),
                    run_id=request.run_id,
                    event_type="composition.candidate-created",
                    phase="materializing",
                    payload={
                        "candidate_id": str(candidate_id),
                        "candidate_snapshot_id": str(snapshot.candidate_snapshot_id),
                        "label": request.label.value,
                        "seed": request.seed,
                        "compiler_version": compiled.compiler_version,
                    },
                    dedupe_key=f"candidate-created:{candidate_id}",
                    created_at=self._clock(),
                )
            )
            return CreateCompositionCandidateResult(
                candidate_id=candidate_id,
                label=request.label,
                seed=request.seed,
                candidate_snapshot_id=snapshot.candidate_snapshot_id,
                candidate_content_hash=snapshot.candidate_content_hash,
                style_pack_version=persisted.style_pack_version,
                compiler_version=compiled.compiler_version,
            )


class CreateCandidateSelectionPreviewRequest(DomainModel):
    run_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    candidate_snapshot_id: UUID
    preview_artifact_id: UUID
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class CreateCandidateSelectionPreviewResult(DomainModel):
    candidate_snapshot_id: UUID
    preview_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: PreviewStatus
    replayed: bool = False


class CreateCandidateSelectionPreview:
    """Bind rendered evidence to a candidate while keeping the Branch unchanged."""

    def __init__(
        self,
        uow_factory: CompositionMaterializationUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        preview_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._preview_ttl = preview_ttl

    async def __call__(
        self, request: CreateCandidateSelectionPreviewRequest
    ) -> CreateCandidateSelectionPreviewResult:
        preview_id = uuid5(
            NAMESPACE_URL,
            f"motif-forge:s5-selection-preview:{request.run_id}:"
            f"{request.candidate_snapshot_id}:v1",
        )
        async with self._uow_factory() as transaction:
            run = await transaction.lock_ai_run(request.run_id)
            _verify_run_target(request, run)
            existing = await transaction.lock_preview(preview_id)
            if existing is not None:
                if (
                    existing.candidate_snapshot_id != request.candidate_snapshot_id
                    or existing.preview_artifact_ids != (request.preview_artifact_id,)
                    or existing.evidence_refs != request.evidence_refs
                ):
                    raise ApplicationError(
                        "CANDIDATE_PREVIEW_CONFLICT",
                        "the stable candidate Preview contains different evidence",
                    )
                return CreateCandidateSelectionPreviewResult(
                    candidate_snapshot_id=existing.candidate_snapshot_id,
                    preview_id=existing.preview_id,
                    candidate_content_hash=existing.candidate_content_hash,
                    status=existing.status,
                    replayed=True,
                )
            snapshot = await transaction.get_candidate_snapshot(request.candidate_snapshot_id)
            if (
                snapshot is None
                or snapshot.project_id != request.project_id
                or snapshot.base_revision_id != request.base_revision_id
                or snapshot.source_run_id != request.run_id
            ):
                raise ApplicationError(
                    "CANDIDATE_IDENTITY_INVALID", "candidate Snapshot does not match the AI run"
                )
            branch = await transaction.lock_branch(
                project_id=request.project_id, branch_id=request.branch_id
            )
            if branch is None:
                raise ApplicationError("BRANCH_NOT_FOUND", "target branch does not exist")
            if branch.head_revision_id != request.base_revision_id:
                raise RevisionConflictError(branch.head_revision_id)
            now = self._clock()
            preview = create_preview_candidate(
                snapshot=snapshot,
                branch=branch,
                actual_change_impact=ChangeImpact.L3,
                preview_id=preview_id,
                created_at=now,
                expires_at=now + self._preview_ttl,
            ).model_copy(
                update={
                    "preview_artifact_ids": (request.preview_artifact_id,),
                    "evidence_refs": request.evidence_refs,
                }
            )
            await transaction.insert_candidate_preview(snapshot=snapshot, preview=preview)
            await transaction.insert_audit_event(
                event_id=uuid4(),
                project_id=request.project_id,
                actor_id=f"agent:candidate-preview:{request.run_id}",
                event_type="project.candidate-preview.created",
                resource_id=preview.preview_id,
                payload={
                    "candidate_snapshot_id": str(snapshot.candidate_snapshot_id),
                    "preview_artifact_id": str(request.preview_artifact_id),
                },
            )
            return CreateCandidateSelectionPreviewResult(
                candidate_snapshot_id=snapshot.candidate_snapshot_id,
                preview_id=preview.preview_id,
                candidate_content_hash=snapshot.candidate_content_hash,
                status=preview.status,
            )


class MaterializeSelectedCompositionCandidateRequest(DomainModel):
    run_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    plan_id: UUID
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_preview_id: UUID
    expected_candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0, le=2**31 - 1)
    actor_id: str = Field(min_length=1, max_length=160)
    selection_assertion: str = Field(min_length=16, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MaterializeSelectedCompositionCandidateResult(DomainModel):
    status: Literal["approved"] = "approved"
    plan_id: UUID
    candidate_snapshot_id: UUID
    preview_id: UUID
    revision_id: UUID
    receipt_id: UUID
    replayed: bool = False


class MaterializeSelectedCompositionCandidate:
    """Atomically commit exactly one selected candidate Preview."""

    def __init__(
        self,
        uow_factory: CompositionMaterializationUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def __call__(
        self, request: MaterializeSelectedCompositionCandidateRequest
    ) -> MaterializeSelectedCompositionCandidateResult:
        fingerprint = request_hash(
            {
                "schema": "selected-composition-materialization.v1",
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        async with self._uow_factory() as transaction:
            run = await transaction.lock_ai_run(request.run_id)
            approval = await transaction.read_ai_run_approval(request.run_id)
            _verify_run_and_plan_approval(request, run, approval)
            receipt = await transaction.read_materialization_receipt(
                run_id=request.run_id,
                plan_id=request.plan_id,
                plan_hash=request.expected_plan_hash,
                seed=request.seed,
            )
            if receipt is not None:
                if (
                    receipt.request_hash != fingerprint
                    or receipt.preview_id != request.selected_preview_id
                    or receipt.actor_id != request.actor_id
                    or receipt.assertion_hash
                    != approval_assertion_hash(request.selection_assertion)
                ):
                    raise ApplicationError(
                        "MATERIALIZATION_REQUEST_CONFLICT",
                        "this candidate was materialized by a different selection",
                    )
                return _materialization_result(receipt, replayed=True)
            if run.status is not AIRunStatus.MATERIALIZING or approval is None:
                raise ApplicationError(
                    "AI_RUN_APPROVAL_CONFLICT", "the live AI run cannot materialize"
                )
            persisted = await transaction.read_composition_plan(
                plan_id=request.plan_id, run_id=request.run_id
            )
            verify_loaded_plan_identity(
                persisted,
                expected_plan_hash=request.expected_plan_hash,
                require_compilation_safe=True,
            )
            preview = await transaction.lock_preview(request.selected_preview_id)
            if preview is None:
                raise ApplicationError("PREVIEW_NOT_FOUND", "selected Preview does not exist")
            snapshot = await transaction.get_candidate_snapshot(preview.candidate_snapshot_id)
            if (
                snapshot is None
                or preview.project_id != request.project_id
                or preview.branch_id != request.branch_id
                or preview.base_revision_id != request.base_revision_id
                or preview.source_run_id != request.run_id
                or snapshot.candidate_content_hash != request.expected_candidate_content_hash
            ):
                raise ApplicationError(
                    "CANDIDATE_IDENTITY_INVALID", "selected candidate does not match the AI run"
                )
            now = self._clock()
            decision = await approve_preview_in_transaction(
                transaction,
                DecidePreviewRequest(
                    preview_id=request.selected_preview_id,
                    decision=PreviewDecision.APPROVE,
                    actor_id=request.actor_id,
                    approval_assertion=request.selection_assertion,
                    idempotency_key=request.idempotency_key,
                ),
                id_factory=uuid4,
                now=now,
            )
            if isinstance(decision, RevisionConflictError):
                raise decision
            if decision.revision_id is None:
                raise ApplicationError("MATERIALIZATION_FAILED", "Revision was not created")
            revision = await transaction.get_revision(decision.revision_id)
            if revision is None or revision.command_batch_id is None:
                raise ApplicationError("MATERIALIZATION_FAILED", "Revision receipt is incomplete")
            compiler_version = snapshot.versions.compiler
            if compiler_version is None:
                raise ApplicationError(
                    "CANDIDATE_IDENTITY_INVALID",
                    "candidate Snapshot is missing its compiler identity",
                )
            receipt = CompositionMaterializationReceipt(
                receipt_id=uuid4(),
                run_id=request.run_id,
                plan_id=request.plan_id,
                plan_content_hash=request.expected_plan_hash,
                plan_hash_version=persisted.hash_version,
                seed=request.seed,
                request_hash=fingerprint,
                actor_id=request.actor_id,
                assertion_hash=approval_assertion_hash(request.selection_assertion),
                candidate_snapshot_id=snapshot.candidate_snapshot_id,
                preview_id=preview.preview_id,
                revision_id=decision.revision_id,
                command_batch_id=revision.command_batch_id,
                style_pack_version=persisted.style_pack_version,
                compiler_version=compiler_version,
                created_at=now,
            )
            await transaction.insert_materialization_receipt(
                receipt,
                AIRunEvent(
                    sequence=1,
                    event_id=uuid4(),
                    run_id=request.run_id,
                    event_type="composition.candidate-selected",
                    phase="materializing",
                    payload={
                        "receipt_id": str(receipt.receipt_id),
                        "plan_id": str(request.plan_id),
                        "candidate_snapshot_id": str(snapshot.candidate_snapshot_id),
                        "preview_id": str(preview.preview_id),
                        "revision_id": str(decision.revision_id),
                        "compiler_version": compiler_version,
                    },
                    dedupe_key=f"candidate-selected:{preview.preview_id}",
                    created_at=now,
                ),
            )
            return _materialization_result(receipt)


class _RunTarget(Protocol):
    @property
    def project_id(self) -> UUID: ...

    @property
    def branch_id(self) -> UUID: ...

    @property
    def base_revision_id(self) -> UUID: ...


class _ApprovedPlanTarget(_RunTarget, Protocol):
    @property
    def expected_plan_hash(self) -> str: ...


def _verify_run_target(request: _RunTarget, run: AIRun) -> None:
    if (
        run.project_id != request.project_id
        or run.branch_id != request.branch_id
        or run.base_revision_id != request.base_revision_id
    ):
        raise ApplicationError(
            "AI_RUN_IDENTITY_INVALID", "the candidate target does not match the AI run"
        )


def _verify_run_and_plan_approval(
    request: _ApprovedPlanTarget, run: AIRun, approval: AIRunApproval | None
) -> None:
    _verify_run_target(request, run)
    if (
        approval is None
        or approval.run_id != run.run_id
        or approval.decision != "approve"
        or approval.expected_plan_content_hash != request.expected_plan_hash
    ):
        raise ApplicationError(
            "AI_RUN_APPROVAL_CONFLICT", "candidate generation requires the approved Plan"
        )


def _materialization_result(
    receipt: CompositionMaterializationReceipt, *, replayed: bool = False
) -> MaterializeSelectedCompositionCandidateResult:
    return MaterializeSelectedCompositionCandidateResult(
        plan_id=receipt.plan_id,
        candidate_snapshot_id=receipt.candidate_snapshot_id,
        preview_id=receipt.preview_id,
        revision_id=receipt.revision_id,
        receipt_id=receipt.receipt_id,
        replayed=replayed,
    )
