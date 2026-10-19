"""Human piano audition workflow; immutable project state changes only on approval."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from motif_forge.application.candidate_previews import (
    CandidatePreviewCursor,
    CollectCandidatePreview,
    EnqueueCandidatePreview,
    EnqueueCandidatePreviewRequest,
)
from motif_forge.application.edit_decisions import AttachEditPreviewArtifact
from motif_forge.application.errors import ApplicationError
from motif_forge.application.media_jobs import CancelMediaJob, CancelMediaJobRequest
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.piano_semantic import PianoSemanticService
from motif_forge.application.ports import MediaJobUnitOfWorkFactory, UnitOfWorkFactory
from motif_forge.application.previews import (
    CreateCommandPreview,
    CreateCommandPreviewRequest,
    DecidePreview,
    DecidePreviewRequest,
    DecidePreviewResult,
    PreviewDecision,
)
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.commands import (
    EditorCommand,
    Selection,
    SetPianoProfileCommand,
    SetPianoProfilePayload,
)
from motif_forge.domain.ir import DomainModel, PerformancePlan, PianoRenderProfile
from motif_forge.domain.piano_requests import PianoSemanticRequest
from motif_forge.domain.revisions import CandidateSnapshot

PianoStep = Literal["baseline", "piano"]


class PianoPreviewRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    request_id: UUID
    render_profile: PianoRenderProfile = Field(default_factory=PianoRenderProfile)
    performance_plan: PerformancePlan = Field(default_factory=PerformancePlan)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    accompaniment: AccompanimentIntent | None = None
    semantic: PianoSemanticRequest | None = None

    @model_validator(mode="after")
    def one_musical_source(self) -> PianoPreviewRequest:
        if self.semantic is not None and (
            self.accompaniment is not None or self.performance_plan.notes
        ):
            raise ValueError("Choose a semantic request or explicit piano controls.")
        return self


class PianoPrepared(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    request_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    preview_id: UUID
    baseline_snapshot_id: UUID
    baseline_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_snapshot_id: UUID
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0, le=2**31 - 1)

    run_id: UUID | None = None
    semantic_summary: str | None = None
    model: str | None = None
    model_requests: int | None = None
    total_tokens: int | None = None
    usage_status: str | None = None


class PianoPreviewDecision(DomainModel):
    action: Literal["approve", "reject"]
    expected_candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_assertion: str = Field(min_length=16, max_length=500)


class PianoPreviewWorkflow:
    def __init__(
        self,
        projects: UnitOfWorkFactory,
        media: MediaJobUnitOfWorkFactory,
        capability: Callable[[], Awaitable[PianoCapability]],
        semantic: PianoSemanticService | None = None,
    ) -> None:
        self._projects, self._media, self._capability = projects, media, capability
        self._semantic = semantic
        self._create, self._decide = CreateCommandPreview(projects), DecidePreview(projects)
        self._enqueue, self._collect = (
            EnqueueCandidatePreview(media),
            CollectCandidatePreview(media),
        )
        self._attach, self._cancel = AttachEditPreviewArtifact(projects), CancelMediaJob(media)

    async def prepare(self, request: PianoPreviewRequest, *, thread_id: str) -> PianoPrepared:
        capability = await self._capability()
        if not capability.available or capability.render_profile != request.render_profile:
            raise ApplicationError(
                capability.error_code or "INSTRUMENT_PACK_UNAVAILABLE",
                "The reviewed piano is not available in the renderer.",
            )
        async with self._projects() as tx:
            base = await tx.get_revision(request.base_revision_id)
            branch = await tx.lock_branch(
                project_id=request.project_id, branch_id=request.branch_id
            )
            if branch is None or branch.head_revision_id != request.base_revision_id:
                raise ApplicationError(
                    "REVISION_CONFLICT", "The saved branch changed before planning."
                )
        if base is None or base.project_id != request.project_id:
            raise ApplicationError("REVISION_NOT_FOUND", "The base revision does not exist.")
        command: EditorCommand
        record = None
        source_run_id = None
        if request.semantic is not None:
            if self._semantic is None:
                raise ApplicationError(
                    "PIANO_SEMANTIC_UNAVAILABLE",
                    "Semantic piano planning requires a durable AI Run.",
                )
            commands, record, source_run_id = await self._semantic.prepare(
                request, base.arrangement_ir, thread_id=thread_id
            )
            command = commands[0]
        elif request.accompaniment is not None:
            from motif_forge.domain.ir import ArrangementIRV2

            if (
                not isinstance(base.arrangement_ir, ArrangementIRV2)
                or request.performance_plan.notes
            ):
                raise ApplicationError(
                    "ACCOMPANIMENT_SOURCE_INVALID",
                    "Choose the saved original melody without expression overrides.",
                )
            command = accompaniment_command(
                base.arrangement_ir, request.accompaniment, request_id=request.request_id
            )
        else:
            command = SetPianoProfileCommand(
                command_id=uuid5(request.request_id, "profile"),
                client_sequence=0,
                selection=Selection(
                    track_ids=tuple(t.track_id for t in base.arrangement_ir.tracks)
                ),
                payload=SetPianoProfilePayload(
                    render_profile=request.render_profile, performance_plan=request.performance_plan
                ),
            )
        preview = await self._create(
            CreateCommandPreviewRequest(
                project_id=request.project_id,
                branch_id=request.branch_id,
                base_revision_id=request.base_revision_id,
                candidate_id=uuid5(request.request_id, "candidate"),
                commands=(command,),
                actor_id="agent:deepseek-piano" if source_run_id else "human:local",
                source_run_id=source_run_id,
                idempotency_key=f"piano-preview:{request.request_id}",
            )
        )
        baseline_id = uuid5(request.request_id, "baseline")
        # A baseline is an audition Snapshot, never a second proposal or an AI Run.
        async with self._projects() as tx:
            await tx.insert_candidate_snapshot(
                CandidateSnapshot(
                    candidate_snapshot_id=baseline_id,
                    candidate_id=baseline_id,
                    project_id=request.project_id,
                    base_revision_id=base.revision_id,
                    candidate_ir=base.arrangement_ir,
                    candidate_content_hash=base.content_hash,
                    versions=base.versions,
                    created_at=base.created_at,
                )
            )
        return PianoPrepared(
            project_id=request.project_id,
            branch_id=request.branch_id,
            base_revision_id=request.base_revision_id,
            request_id=request.request_id,
            thread_id=thread_id,
            preview_id=preview.preview_id,
            baseline_snapshot_id=baseline_id,
            baseline_content_hash=base.content_hash,
            candidate_snapshot_id=preview.candidate_snapshot_id,
            candidate_content_hash=preview.candidate_content_hash,
            seed=request.seed,
            run_id=source_run_id,
            semantic_summary=record["plan"]["summary"] if record else None,
            model=record["model"] if record else None,
            model_requests=1 if record else None,
            total_tokens=record["usage"]["total_tokens"] if record else None,
            usage_status=record["usage"]["status"] if record else None,
        )

    async def enqueue(self, prepared: PianoPrepared, *, step: PianoStep) -> CandidatePreviewCursor:
        baseline = step == "baseline"
        return await self._enqueue(
            EnqueueCandidatePreviewRequest(
                project_id=prepared.project_id,
                candidate_snapshot_id=prepared.baseline_snapshot_id
                if baseline
                else prepared.candidate_snapshot_id,
                expected_candidate_content_hash=prepared.baseline_content_hash
                if baseline
                else prepared.candidate_content_hash,
                thread_id=prepared.thread_id,
                seed=prepared.seed,
                run_type="parent.piano_preview.v1",
                idempotency_key=f"piano-preview:{prepared.request_id}:{step}",
            )
        )

    async def collect(
        self, prepared: PianoPrepared, cursor: CandidatePreviewCursor, *, step: PianoStep
    ) -> CandidatePreviewCursor:
        self._check_cursor(prepared, cursor, step)
        collected = await self._collect(cursor, cursor.job_id)
        if step == "piano":
            assert collected.preview_artifact_id is not None
            attach = self._attach
            if prepared.run_id is not None and self._semantic is not None:
                attach = AttachEditPreviewArtifact(
                    self._projects, run_id=prepared.run_id, ai_uow_factory=self._semantic.ai_uow
                )
            await attach(
                preview_id=prepared.preview_id,
                candidate_snapshot_id=prepared.candidate_snapshot_id,
                expected_candidate_content_hash=prepared.candidate_content_hash,
                preview_artifact_id=collected.preview_artifact_id,
            )
        return collected

    @staticmethod
    def _check_cursor(
        prepared: PianoPrepared, cursor: CandidatePreviewCursor, step: PianoStep
    ) -> None:
        if (
            cursor.project_id != prepared.project_id
            or cursor.candidate_snapshot_id
            != (
                prepared.baseline_snapshot_id
                if step == "baseline"
                else prepared.candidate_snapshot_id
            )
            or cursor.candidate_content_hash
            != (
                prepared.baseline_content_hash
                if step == "baseline"
                else prepared.candidate_content_hash
            )
        ):
            raise ApplicationError(
                "PIANO_PREVIEW_LINEAGE_MISMATCH", "Audition belongs to another candidate."
            )

    async def decide(
        self,
        prepared: PianoPrepared,
        decision: PianoPreviewDecision,
        cursor: CandidatePreviewCursor,
    ) -> DecidePreviewResult:
        if decision.expected_candidate_content_hash != prepared.candidate_content_hash:
            raise ApplicationError(
                "PIANO_CANDIDATE_HASH_MISMATCH", "Approval must bind the exact candidate."
            )
        if decision.action == "approve":
            self._check_cursor(prepared, cursor, "piano")
            collected = await self._collect(cursor, cursor.job_id)
            async with self._projects() as tx:
                preview = await tx.lock_preview(prepared.preview_id)
            if (
                preview is None
                or preview.project_id != prepared.project_id
                or preview.candidate_snapshot_id != prepared.candidate_snapshot_id
                or preview.candidate_content_hash != prepared.candidate_content_hash
                or preview.preview_artifact_ids != (collected.preview_artifact_id,)
            ):
                raise ApplicationError(
                    "PIANO_PREVIEW_ARTIFACT_REQUIRED",
                    "Approval requires the completed piano audition.",
                )
        return await self._decide(
            DecidePreviewRequest(
                preview_id=prepared.preview_id,
                decision=PreviewDecision(decision.action),
                actor_id="human:local",
                approval_assertion=decision.approval_assertion,
                idempotency_key=f"piano-decision:{prepared.request_id}:{decision.action}",
            )
        )

    async def cancel(self, prepared: PianoPrepared, cursor: CandidatePreviewCursor) -> None:
        await self._cancel(CancelMediaJobRequest(job_id=cursor.job_id, actor_id="human:local"))
        await self._decide(
            DecidePreviewRequest(
                preview_id=prepared.preview_id,
                decision=PreviewDecision.REJECT,
                actor_id="human:local",
                approval_assertion="The user cancelled this piano audition.",
                idempotency_key=f"piano-decision:{prepared.request_id}:cancel",
            )
        )
