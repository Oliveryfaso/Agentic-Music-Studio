"""Approval-gated deterministic complete-song preparation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field

from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.application.previews import (
    CreateCommandPreview,
    CreateCommandPreviewRequest,
    CreateCommandPreviewResult,
)
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.ir import ArrangementIR, DomainModel
from motif_forge.domain.revisions import (
    ChangeImpact,
    PreviewStatus,
    StructuralDiffEntry,
    VersionRefs,
)


class PrepareDeterministicCompositionPreviewRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    seed: int = Field(ge=0, le=2**31 - 1)
    actor_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)


class PrepareDeterministicCompositionPreviewResult(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    candidate_snapshot_id: UUID
    preview_id: UUID
    actual_change_impact: ChangeImpact
    status: PreviewStatus
    arrangement: ArrangementIR
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_seconds: float = Field(gt=0.0, le=300.0, allow_inf_nan=False)
    replayed: bool = False


class PrepareDeterministicCompositionPreview:
    """Build an S1 candidate and route it through the existing L3 Preview/HITL path."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def __call__(
        self, request: PrepareDeterministicCompositionPreviewRequest
    ) -> PrepareDeterministicCompositionPreviewResult:
        build = build_s1_composition(request.project_id, seed=request.seed)
        candidate_id = uuid5(
            NAMESPACE_URL,
            f"motif-forge:s1-candidate:{request.project_id}:{request.base_revision_id}:"
            f"{request.seed}",
        )
        preview = await CreateCommandPreview(
            self._uow_factory,
            clock=self._clock,
            versions=VersionRefs(
                audio_engine="motif-forge-audio-engine.v1",
                policy="change-impact.v1",
                assets="builtin-seed-palette.v1",
            ),
        )(
            CreateCommandPreviewRequest(
                project_id=request.project_id,
                branch_id=request.branch_id,
                base_revision_id=request.base_revision_id,
                candidate_id=candidate_id,
                commands=build.commands,
                actor_id=request.actor_id,
                idempotency_key=request.idempotency_key,
                structural_diff=(
                    StructuralDiffEntry(
                        operation="replace",
                        path="/arrangement",
                        summary="Generate deterministic 24-bar Synth Ambient composition",
                    ),
                ),
            )
        )
        return PrepareDeterministicCompositionPreviewResult(
            project_id=preview.project_id,
            branch_id=preview.branch_id,
            base_revision_id=preview.base_revision_id,
            candidate_snapshot_id=preview.candidate_snapshot_id,
            preview_id=preview.preview_id,
            actual_change_impact=preview.actual_change_impact,
            status=preview.status,
            arrangement=build.arrangement,
            content_hash=build.content_hash,
            duration_seconds=build.duration_seconds,
            replayed=preview.replayed,
        )


class PreparePlanDrivenCompositionPreview:
    """Route a precompiled, policy-validated Plan build through the existing L3 Preview path."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._create = CreateCommandPreview(
            uow_factory,
            clock=clock,
            versions=VersionRefs(
                policy="change-impact.v1",
                audio_engine="motif-forge-audio-engine.v1",
                graph="motif-forge-parent.v2",
                knowledge="synth-ambient.v1",
                assets="builtin-seed-palette.v1",
            ),
        )

    async def __call__(self, request: CreateCommandPreviewRequest) -> CreateCommandPreviewResult:
        """Create the immutable Candidate/Preview without writing a Revision."""

        return await self._create(request)
