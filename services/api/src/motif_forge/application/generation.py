"""Persist validated plans and materialize only a matching human-approved composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, PlanningResult
from motif_forge.application.ai_runs import PersistCompositionPlan
from motif_forge.application.composition import PreparePlanDrivenCompositionPreview
from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import AIRunUnitOfWorkFactory, UnitOfWorkFactory
from motif_forge.application.previews import (
    CreateCommandPreviewRequest,
    CreateCommandPreviewResult,
    DecidePreview,
    DecidePreviewRequest,
    DecidePreviewResult,
    PreviewDecision,
)
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V1,
    PLAN_HASH_VERSION_V2,
    AIRun,
    AIRunApproval,
    AIRunStatus,
    PersistedCompositionPlan,
    approval_assertion_hash,
    canonical_plan_json_bytes,
    composition_plan_content_hash,
)
from motif_forge.domain.composition import (
    CompositionBuild,
    SynthAmbientCompilationError,
    compile_synth_ambient_plan,
)
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.revisions import (
    ChangeImpact,
    PreviewStatus,
    StructuralDiffEntry,
)


class PersistPlanningResultRequest(DomainModel):
    run_id: UUID
    expected_run_version: int = Field(ge=0)
    planning_result: PlanningResult
    style_pack_version: str = Field(default="synth-ambient.v1", min_length=1, max_length=80)


class PersistPlanningResultResult(DomainModel):
    run_id: UUID
    plan_id: UUID
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_version: Literal["composition-plan-hash.lossless-v2"] = "composition-plan-hash.lossless-v2"
    interrupt_ref: str = Field(min_length=16, max_length=160)
    run_version: int = Field(ge=1)


class PersistPlanningResult:
    """Revalidate a bounded planning result, persist v2 identity, and open one interrupt."""

    def __init__(
        self,
        ai_run_uow_factory: AIRunUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ai_run_uow_factory = ai_run_uow_factory
        self._id_factory = id_factory
        self._clock = clock

    async def __call__(self, request: PersistPlanningResultRequest) -> PersistPlanningResultResult:
        result = request.planning_result
        if result.get("phase") != "planning_complete" or "plan" not in result:
            raise ApplicationError(
                "PLANNING_RESULT_INVALID",
                "only a completed, schema-valid planning result may be persisted",
            )
        try:
            plan = CompositionPlan.model_validate_json(json.dumps(result["plan"]), strict=True)
        except ValueError as exc:
            raise ApplicationError(
                "PLANNING_RESULT_INVALID", "the planning result does not contain a valid Plan"
            ) from exc
        metadata = result.get("provider_metadata", {})
        required = ("provider", "model", "prompt_version", "schema_version")
        if any(not isinstance(metadata.get(key), str) or not metadata[key] for key in required):
            raise ApplicationError(
                "PLANNING_RESULT_INVALID", "the planning result provenance is incomplete"
            )
        if metadata["schema_version"] != plan.schema_version:
            raise ApplicationError(
                "PLANNING_RESULT_INVALID", "the Plan and provider schema versions disagree"
            )
        plan_hash = composition_plan_content_hash(plan, hash_version=PLAN_HASH_VERSION_V2)
        persisted = await PersistCompositionPlan(self._ai_run_uow_factory)(
            PersistedCompositionPlan(
                plan_id=self._id_factory(),
                run_id=request.run_id,
                plan=plan,
                content_hash=plan_hash,
                hash_version=PLAN_HASH_VERSION_V2,
                provider=metadata["provider"],
                model=metadata["model"],
                prompt_version=metadata["prompt_version"],
                schema_version=metadata["schema_version"],
                style_pack_version=request.style_pack_version,
                fallback_reason=result.get("fallback_reason"),
                created_at=self._clock(),
            )
        )
        async with self._ai_run_uow_factory() as transaction:
            run = await transaction.mark_ai_run_plan_pending(
                run_id=request.run_id,
                plan_id=persisted.plan_id,
                expected_version=request.expected_run_version,
                now=self._clock(),
            )
        if (
            run.pending_plan_id != persisted.plan_id
            or run.pending_plan_content_hash != persisted.content_hash
            or run.pending_interrupt_ref is None
        ):
            raise ApplicationError(
                "AI_RUN_PLAN_CONFLICT", "the authoritative pending Plan identity is inconsistent"
            )
        return PersistPlanningResultResult(
            run_id=request.run_id,
            plan_id=persisted.plan_id,
            plan_hash=persisted.content_hash,
            interrupt_ref=run.pending_interrupt_ref,
            run_version=run.version,
        )


class LoadCompositionPlan:
    def __init__(self, ai_run_uow_factory: AIRunUnitOfWorkFactory) -> None:
        self._ai_run_uow_factory = ai_run_uow_factory

    async def __call__(
        self,
        *,
        run_id: UUID,
        plan_id: UUID,
        expected_plan_hash: str,
        require_compilation_safe: bool = False,
    ) -> PersistedCompositionPlan:
        async with self._ai_run_uow_factory() as transaction:
            persisted = await transaction.read_composition_plan(plan_id=plan_id, run_id=run_id)
        actual = composition_plan_content_hash(persisted.plan, hash_version=persisted.hash_version)
        if actual != persisted.content_hash or persisted.content_hash != expected_plan_hash:
            raise ApplicationError(
                "PLAN_HASH_MISMATCH",
                "the immutable CompositionPlan does not match its approved identity",
            )
        if require_compilation_safe and persisted.hash_version == PLAN_HASH_VERSION_V1:
            v1_bytes = canonical_plan_json_bytes(persisted.plan, hash_version=PLAN_HASH_VERSION_V1)
            v2_bytes = canonical_plan_json_bytes(persisted.plan, hash_version=PLAN_HASH_VERSION_V2)
            if v1_bytes != v2_bytes:
                raise ApplicationError(
                    "PLAN_HASH_VERSION_UNSAFE",
                    "this legacy Plan identity is lossy and must be replanned before compilation",
                )
        return persisted


class MaterializeApprovedCompositionRequest(DomainModel):
    run_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    plan_id: UUID
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0, le=2**31 - 1)
    actor_id: str = Field(min_length=1, max_length=160)
    approval_assertion: str = Field(min_length=16, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MaterializeApprovedCompositionResult(DomainModel):
    status: Literal["approved", "rejected"]
    plan_id: UUID
    candidate_snapshot_id: UUID | None = None
    preview_id: UUID | None = None
    revision_id: UUID | None = None
    replayed: bool = False


Compiler = Callable[..., CompositionBuild]
CreatePreview = Callable[[CreateCommandPreviewRequest], Awaitable[CreateCommandPreviewResult]]
Decide = Callable[[DecidePreviewRequest], Awaitable[DecidePreviewResult]]


class MaterializeApprovedComposition:
    """Compile and materialize through the existing Preview transaction after authorization."""

    def __init__(
        self,
        ai_run_uow_factory: AIRunUnitOfWorkFactory,
        project_uow_factory: UnitOfWorkFactory,
        *,
        compiler: Compiler = compile_synth_ambient_plan,
        create_preview: CreatePreview | None = None,
        decide_preview: Decide | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ai_run_uow_factory = ai_run_uow_factory
        self._project_uow_factory = project_uow_factory
        self._compiler = compiler
        self._create_preview = create_preview or PreparePlanDrivenCompositionPreview(
            project_uow_factory, clock=clock
        )
        self._decide_preview = decide_preview or DecidePreview(project_uow_factory, clock=clock)

    async def __call__(
        self, request: MaterializeApprovedCompositionRequest
    ) -> MaterializeApprovedCompositionResult:
        run, approval = await self._load_authorization(request.run_id)
        self._verify_request_identity(request, run, approval)
        persisted = await LoadCompositionPlan(self._ai_run_uow_factory)(
            run_id=request.run_id,
            plan_id=request.plan_id,
            expected_plan_hash=request.expected_plan_hash,
            require_compilation_safe=approval.decision == "approve",
        )
        if approval.decision == "reject":
            if run.status is not AIRunStatus.REJECTED:
                raise ApplicationError(
                    "AI_RUN_APPROVAL_CONFLICT", "the rejected decision is not authoritative"
                )
            return MaterializeApprovedCompositionResult(status="rejected", plan_id=request.plan_id)
        if approval.decision != "approve" or run.status is not AIRunStatus.MATERIALIZING:
            raise ApplicationError(
                "AI_RUN_APPROVAL_CONFLICT", "the AI run has no materialization authorization"
            )
        if run.brief is None:
            raise ApplicationError(
                "BRIEF_NOT_FOUND", "the authoritative composition brief is missing"
            )
        try:
            brief = CompositionBrief.model_validate_json(json.dumps(run.brief), strict=True)
        except ValueError as exc:
            raise ApplicationError(
                "BRIEF_INVALID", "the authoritative composition brief is invalid"
            ) from exc
        try:
            build = self._compiler(
                request.project_id, brief=brief, plan=persisted.plan, seed=request.seed
            )
        except SynthAmbientCompilationError as exc:
            raise ApplicationError(
                "PLAN_STRATEGY_INCOMPATIBLE",
                "the approved CompositionPlan no longer satisfies the strategy policy",
            ) from exc
        candidate_id = uuid5(
            NAMESPACE_URL,
            f"motif-forge:s2-candidate:{request.run_id}:{request.plan_id}:"
            f"{request.expected_plan_hash}:{request.seed}",
        )
        key_digest = hashlib.sha256(
            (
                f"{request.run_id}:{request.plan_id}:{request.seed}:{request.idempotency_key}"
            ).encode()
        ).hexdigest()
        preview = await self._create_preview(
            CreateCommandPreviewRequest(
                project_id=request.project_id,
                branch_id=request.branch_id,
                base_revision_id=request.base_revision_id,
                candidate_id=candidate_id,
                commands=build.commands,
                actor_id=f"agent:plan-compiler:{request.run_id}",
                idempotency_key=f"s2-preview:{key_digest}",
                source_run_id=request.run_id,
                structural_diff=(
                    StructuralDiffEntry(
                        operation="replace",
                        path="/arrangement",
                        summary="Materialize the approved Synth Ambient CompositionPlan",
                    ),
                ),
            )
        )
        if preview.actual_change_impact is not ChangeImpact.L3:
            raise ApplicationError(
                "CHANGE_IMPACT_INVALID", "from-zero generation must remain an L3 change"
            )
        decision = await self._decide_preview(
            DecidePreviewRequest(
                preview_id=preview.preview_id,
                decision=PreviewDecision.APPROVE,
                actor_id=request.actor_id,
                approval_assertion=request.approval_assertion,
                idempotency_key=f"s2-approve:{key_digest}",
            )
        )
        if decision.status is not PreviewStatus.APPROVED or decision.revision_id is None:
            raise ApplicationError(
                "MATERIALIZATION_FAILED", "approved candidate did not produce an immutable Revision"
            )
        return MaterializeApprovedCompositionResult(
            status="approved",
            plan_id=request.plan_id,
            candidate_snapshot_id=preview.candidate_snapshot_id,
            preview_id=preview.preview_id,
            revision_id=decision.revision_id,
            replayed=preview.replayed or decision.replayed,
        )

    async def _load_authorization(self, run_id: UUID) -> tuple[AIRun, AIRunApproval]:
        async with self._ai_run_uow_factory() as transaction:
            run = await transaction.read_ai_run(run_id)
            approval = await transaction.read_ai_run_approval(run_id)
        if approval is None:
            raise ApplicationError(
                "AI_RUN_APPROVAL_REQUIRED", "materialization requires a persisted human decision"
            )
        return run, approval

    @staticmethod
    def _verify_request_identity(
        request: MaterializeApprovedCompositionRequest,
        run: AIRun,
        approval: AIRunApproval,
    ) -> None:
        if (
            run.project_id != request.project_id
            or run.branch_id != request.branch_id
            or run.base_revision_id != request.base_revision_id
        ):
            raise ApplicationError(
                "AI_RUN_IDENTITY_INVALID", "the materialization target does not match the AI run"
            )
        if (
            approval.run_id != request.run_id
            or approval.actor_id != request.actor_id
            or approval.assertion_hash != approval_assertion_hash(request.approval_assertion)
            or approval.expected_plan_content_hash != request.expected_plan_hash
        ):
            raise ApplicationError(
                "AI_RUN_APPROVAL_CONFLICT", "the request does not match persisted authorization"
            )
