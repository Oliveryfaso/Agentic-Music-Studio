"""Persist validated plans and materialize only a matching human-approved composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field, model_validator

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, PlanningResult
from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, RevisionConflictError
from motif_forge.application.media_jobs import (
    EnqueueFollowupMediaJob,
    EnqueueFollowupMediaJobRequest,
    EnqueueMediaJob,
    EnqueueMediaJobRequest,
)
from motif_forge.application.ports import (
    AIRunUnitOfWorkFactory,
    CompositionMaterializationUnitOfWorkFactory,
    MediaJobUnitOfWorkFactory,
)
from motif_forge.application.previews import (
    CreateCommandPreviewRequest,
    DecidePreviewRequest,
    PreviewDecision,
    approve_preview_in_transaction,
    create_command_preview_in_transaction,
)
from motif_forge.application.rendering import (
    AUDIO_ENGINE_VERSION,
    build_canonical_render_payload,
)
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V1,
    PLAN_HASH_VERSION_V2,
    AIRun,
    AIRunApproval,
    AIRunEvent,
    AIRunStatus,
    CompositionMaterializationReceipt,
    PersistedCompositionPlan,
    approval_assertion_hash,
    canonical_plan_json_bytes,
    composition_plan_content_hash,
)
from motif_forge.domain.composition import (
    SYNTH_AMBIENT_COMPILER_VERSION,
    CompositionBuild,
    SynthAmbientCompilationError,
    compile_synth_ambient_plan,
)
from motif_forge.domain.ir import DomainModel, TrackRole
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    AudioArtifact,
    BundleAudioInput,
    ExportBundleArtifact,
    ExportBundleJobPayload,
    ExportMp3JobPayload,
    JobStatus,
    MediaJobType,
    MediaQualityProfile,
    RenderScope,
)
from motif_forge.domain.revisions import (
    Revision,
    StructuralDiffEntry,
    VersionRefs,
)

_EXPORT_STEPS = (
    "master",
    "stem:pad",
    "stem:melody",
    "stem:bass",
    "stem:rhythm",
    "mp3",
    "bundle",
)
_ROLE_BY_STEP = {
    "stem:pad": TrackRole.HARMONY,
    "stem:melody": TrackRole.MELODY,
    "stem:bass": TrackRole.BASS,
    "stem:rhythm": TrackRole.RHYTHM,
}


class CompleteExportCursor(DomainModel):
    """Compact checkpoint-safe state for one finite complete-song export."""

    schema_version: Literal["complete-export-cursor.v1"] = "complete-export-cursor.v1"
    project_id: UUID
    revision_id: UUID
    thread_id: str = Field(min_length=1, max_length=160)
    seed: int = Field(ge=0, le=2**31 - 1)
    media_run_id: UUID | None = None
    pending_job_id: UUID | None = None
    pending_idempotency_key: str | None = None
    completed_steps: tuple[str, ...] = ()
    completed_job_ids: tuple[UUID, ...] = ()
    audio_artifact_ids: tuple[UUID, ...] = ()
    bundle_artifact_id: UUID | None = None

    @model_validator(mode="after")
    def validate_progress(self) -> CompleteExportCursor:
        completed_count = len(self.completed_steps)
        if self.completed_steps != _EXPORT_STEPS[:completed_count]:
            raise ValueError("completed_steps must be an ordered export prefix")
        if len(self.completed_job_ids) != completed_count:
            raise ValueError("completed Job count must match completed steps")
        expected_audio_count = min(completed_count, 6)
        if len(self.audio_artifact_ids) != expected_audio_count:
            raise ValueError("completed audio Artifact count is inconsistent")
        if len(set(self.completed_job_ids)) != len(self.completed_job_ids) or len(
            set(self.audio_artifact_ids)
        ) != len(self.audio_artifact_ids):
            raise ValueError("completed export identities must be unique")
        if completed_count == 7:
            if self.bundle_artifact_id is None:
                raise ValueError("completed export requires its Bundle Artifact")
        elif self.bundle_artifact_id is not None:
            raise ValueError("Bundle Artifact is valid only after bundle completion")
        pending_fields = (self.pending_job_id, self.pending_idempotency_key)
        if (pending_fields[0] is None) != (pending_fields[1] is None):
            raise ValueError("pending Job identity must be complete")
        has_progress = completed_count > 0 or self.pending_job_id is not None
        if has_progress != (self.media_run_id is not None):
            raise ValueError("export progress must belong to one MediaRun")
        return self

    @property
    def pending_steps(self) -> tuple[str, ...]:
        return _EXPORT_STEPS[len(self.completed_steps) :]


def _export_key(cursor: CompleteExportCursor, step: str) -> str:
    digest = hashlib.sha256(
        f"complete-export.v1:{cursor.project_id}:{cursor.revision_id}:{cursor.seed}:{step}".encode()
    ).hexdigest()
    return f"complete-export:{digest}"


async def _load_revision(
    uow_factory: MediaJobUnitOfWorkFactory,
    *,
    project_id: UUID,
    revision_id: UUID,
) -> Revision:
    async with uow_factory() as transaction:
        revision = await transaction.get_revision(revision_id)
    if revision is None or revision.project_id != project_id:
        raise ApplicationError("EXPORT_REVISION_NOT_FOUND", "the authoritative Revision is missing")
    return revision


def _track_id_for_step(revision: Revision, step: str) -> UUID:
    role = _ROLE_BY_STEP[step]
    matches = tuple(
        track.track_id for track in revision.arrangement_ir.tracks if track.role is role
    )
    if len(matches) != 1:
        raise ApplicationError(
            "EXPORT_RENDER_SCOPE_INVALID",
            f"complete export requires exactly one {role.value} track",
        )
    return matches[0]


def _verify_audio_lineage(
    artifact: AudioArtifact,
    *,
    revision: Revision,
    profile: MediaQualityProfile,
    render_scope: RenderScope,
    render_track_ids: tuple[UUID, ...],
    source_job_id: UUID | None = None,
) -> None:
    if (
        artifact.project_id != revision.project_id
        or artifact.revision_id != revision.revision_id
        or artifact.arrangement_hash != revision.content_hash
        or artifact.quality_profile is not profile
        or artifact.render_scope is not render_scope
        or artifact.render_track_ids != render_track_ids
        or artifact.availability is not ArtifactAvailability.AVAILABLE
        or (source_job_id is not None and artifact.source_job_id != source_job_id)
    ):
        raise ApplicationError(
            "EXPORT_ARTIFACT_LINEAGE_MISMATCH",
            "the completed Artifact does not belong to this Revision export",
        )


def _bundle_input(artifact: AudioArtifact, *, filename: str) -> BundleAudioInput:
    profile = artifact.quality_profile
    if profile not in {
        MediaQualityProfile.CANONICAL_MASTER_V1,
        MediaQualityProfile.CANONICAL_STEM_V1,
        MediaQualityProfile.DELIVERY_MP3_V1,
    }:
        raise ApplicationError(
            "EXPORT_ARTIFACT_PROFILE_INVALID", "Artifact cannot enter a complete export"
        )
    return BundleAudioInput(
        artifact_id=artifact.artifact_id,
        quality_profile=cast(
            "Literal[MediaQualityProfile.CANONICAL_MASTER_V1, "
            "MediaQualityProfile.CANONICAL_STEM_V1, "
            "MediaQualityProfile.DELIVERY_MP3_V1]",
            profile,
        ),
        content_hash=artifact.content_hash,
        filename=filename,
    )


def build_export_bundle_payload(
    *,
    revision: Revision,
    seed: int,
    artifacts: tuple[AudioArtifact, ...],
    trace_refs: tuple[str, ...],
) -> ExportBundleJobPayload:
    """Build a logical Bundle request containing references, never copied audio bytes/paths."""

    by_profile = {
        MediaQualityProfile.CANONICAL_MASTER_V1: tuple(
            item
            for item in artifacts
            if item.quality_profile is MediaQualityProfile.CANONICAL_MASTER_V1
        ),
        MediaQualityProfile.DELIVERY_MP3_V1: tuple(
            item
            for item in artifacts
            if item.quality_profile is MediaQualityProfile.DELIVERY_MP3_V1
        ),
    }
    masters = by_profile[MediaQualityProfile.CANONICAL_MASTER_V1]
    mp3s = by_profile[MediaQualityProfile.DELIVERY_MP3_V1]
    stems = tuple(
        item for item in artifacts if item.quality_profile is MediaQualityProfile.CANONICAL_STEM_V1
    )
    if len(masters) != 1 or len(mp3s) != 1 or len(stems) != 4:
        raise ApplicationError(
            "EXPORT_ARTIFACT_SET_INCOMPLETE", "complete export requires six audio Artifacts"
        )
    _verify_audio_lineage(
        masters[0],
        revision=revision,
        profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
    )
    _verify_audio_lineage(
        mp3s[0],
        revision=revision,
        profile=MediaQualityProfile.DELIVERY_MP3_V1,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
    )
    stem_by_track = {
        item.render_track_ids[0]: item for item in stems if len(item.render_track_ids) == 1
    }
    ordered_stems: list[tuple[str, AudioArtifact]] = []
    for step in _EXPORT_STEPS[1:5]:
        track_id = _track_id_for_step(revision, step)
        artifact = stem_by_track.get(track_id)
        if artifact is None:
            raise ApplicationError("EXPORT_ARTIFACT_SET_INCOMPLETE", "one required Stem is missing")
        _verify_audio_lineage(
            artifact,
            revision=revision,
            profile=MediaQualityProfile.CANONICAL_STEM_V1,
            render_scope=RenderScope.STEM,
            render_track_ids=(track_id,),
        )
        ordered_stems.append((step.removeprefix("stem:"), artifact))
    inputs = (
        _bundle_input(masters[0], filename="master.wav"),
        _bundle_input(mp3s[0], filename="master.mp3"),
        *tuple(_bundle_input(item, filename=f"stem-{role}.wav") for role, item in ordered_stems),
    )
    return ExportBundleJobPayload(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        seed=seed,
        arrangement_hash=revision.content_hash,
        audio_inputs=inputs,
        engine_version=AUDIO_ENGINE_VERSION,
        trace_refs=trace_refs,
    )


class EnqueueNextCompleteExportJob:
    """Reload truth and enqueue exactly the next step of a finite export chain."""

    def __init__(
        self,
        media_uow_factory: MediaJobUnitOfWorkFactory,
        *,
        enqueue_first: EnqueueMediaJob,
        enqueue_followup: EnqueueFollowupMediaJob,
    ) -> None:
        self._uow_factory = media_uow_factory
        self._enqueue_first = enqueue_first
        self._enqueue_followup = enqueue_followup

    async def __call__(self, cursor: CompleteExportCursor) -> CompleteExportCursor:
        if cursor.pending_job_id is not None or not cursor.pending_steps:
            return cursor
        revision = await _load_revision(
            self._uow_factory,
            project_id=cursor.project_id,
            revision_id=cursor.revision_id,
        )
        await self._verify_collected_audio(cursor, revision=revision)
        step = cursor.pending_steps[0]
        key = _export_key(cursor, step)
        job_type: MediaJobType
        quality: MediaQualityProfile
        payload: dict[str, object]
        deadline: int
        if step == "master" or step.startswith("stem:"):
            track_ids = () if step == "master" else (_track_id_for_step(revision, step),)
            render = build_canonical_render_payload(
                revision,
                seed=cursor.seed,
                render_track_ids=track_ids,
            )
            job_type = MediaJobType.RENDER_CANONICAL
            quality = render.quality_profile
            payload = render.model_dump(mode="json")
            deadline = 300
        elif step == "mp3":
            artifacts = await self._load_audio_artifacts(cursor.audio_artifact_ids)
            if len(artifacts) != 5:
                raise ApplicationError(
                    "EXPORT_ARTIFACT_SET_INCOMPLETE", "Master and Stems must complete before MP3"
                )
            master = next(
                (
                    item
                    for item in artifacts
                    if item.quality_profile is MediaQualityProfile.CANONICAL_MASTER_V1
                ),
                None,
            )
            if master is None:
                raise ApplicationError("EXPORT_ARTIFACT_SET_INCOMPLETE", "Master is missing")
            _verify_audio_lineage(
                master,
                revision=revision,
                profile=MediaQualityProfile.CANONICAL_MASTER_V1,
                render_scope=RenderScope.MASTER,
                render_track_ids=(),
            )
            transcode = ExportMp3JobPayload(
                project_id=revision.project_id,
                revision_id=revision.revision_id,
                source_artifact_id=master.artifact_id,
                source_content_hash=master.content_hash,
                timeout_seconds=180,
            )
            job_type = MediaJobType.TRANSCODE_EXPORT
            quality = MediaQualityProfile.DELIVERY_MP3_V1
            payload = transcode.model_dump(mode="json")
            deadline = 240
        else:
            artifacts = await self._load_audio_artifacts(cursor.audio_artifact_ids)
            bundle = build_export_bundle_payload(
                revision=revision,
                seed=cursor.seed,
                artifacts=artifacts,
                trace_refs=(
                    f"run:{cursor.media_run_id}",
                    *(f"job:{job_id}" for job_id in cursor.completed_job_ids),
                ),
            )
            job_type = MediaJobType.EXPORT_BUNDLE
            quality = MediaQualityProfile.EXPORT_BUNDLE_V1
            payload = bundle.model_dump(mode="json")
            deadline = 240
        if cursor.media_run_id is None:
            result = await self._enqueue_first(
                EnqueueMediaJobRequest(
                    project_id=cursor.project_id,
                    thread_id=cursor.thread_id,
                    run_type="complete_song_export.v1",
                    job_type=job_type,
                    input_payload=payload,
                    output_quality_profile=quality,
                    idempotency_key=key,
                    deadline_seconds=deadline,
                )
            )
        else:
            result = await self._enqueue_followup(
                EnqueueFollowupMediaJobRequest(
                    run_id=cursor.media_run_id,
                    project_id=cursor.project_id,
                    thread_id=cursor.thread_id,
                    job_type=job_type,
                    input_payload=payload,
                    output_quality_profile=quality,
                    idempotency_key=key,
                    deadline_seconds=deadline,
                )
            )
        return cursor.model_copy(
            update={
                "media_run_id": result.run_id,
                "pending_job_id": result.job_id,
                "pending_idempotency_key": key,
            }
        )

    async def _load_audio_artifacts(
        self, artifact_ids: tuple[UUID, ...]
    ) -> tuple[AudioArtifact, ...]:
        async with self._uow_factory() as transaction:
            values = tuple([await transaction.get_audio_artifact(item) for item in artifact_ids])
        if any(item is None for item in values):
            raise ApplicationError("EXPORT_ARTIFACT_NOT_FOUND", "an export Artifact is missing")
        return tuple(item for item in values if item is not None)

    async def _verify_collected_audio(
        self,
        cursor: CompleteExportCursor,
        *,
        revision: Revision,
    ) -> None:
        artifacts = await self._load_audio_artifacts(cursor.audio_artifact_ids)
        for step, job_id, artifact in zip(
            cursor.completed_steps[:6],
            cursor.completed_job_ids[:6],
            artifacts,
            strict=True,
        ):
            if step == "master":
                profile = MediaQualityProfile.CANONICAL_MASTER_V1
                scope = RenderScope.MASTER
                track_ids: tuple[UUID, ...] = ()
            elif step.startswith("stem:"):
                profile = MediaQualityProfile.CANONICAL_STEM_V1
                scope = RenderScope.STEM
                track_ids = (_track_id_for_step(revision, step),)
            else:
                profile = MediaQualityProfile.DELIVERY_MP3_V1
                scope = RenderScope.MASTER
                track_ids = ()
            _verify_audio_lineage(
                artifact,
                revision=revision,
                profile=profile,
                render_scope=scope,
                render_track_ids=track_ids,
                source_job_id=job_id,
            )


class CollectCompleteExportArtifact:
    """Validate one authoritative completion and advance the cursor exactly once."""

    def __init__(self, media_uow_factory: MediaJobUnitOfWorkFactory) -> None:
        self._uow_factory = media_uow_factory

    async def __call__(
        self,
        cursor: CompleteExportCursor,
        *,
        completed_job_id: UUID | None = None,
    ) -> CompleteExportCursor:
        job_id = completed_job_id or cursor.pending_job_id
        if job_id is None:
            raise ApplicationError("EXPORT_JOB_NOT_PENDING", "there is no pending export Job")
        if job_id in cursor.completed_job_ids:
            return cursor
        if cursor.pending_job_id != job_id or not cursor.pending_steps:
            raise ApplicationError(
                "EXPORT_JOB_MISMATCH", "completion does not match the pending export Job"
            )
        revision = await _load_revision(
            self._uow_factory,
            project_id=cursor.project_id,
            revision_id=cursor.revision_id,
        )
        async with self._uow_factory() as transaction:
            job = await transaction.get_media_job(job_id)
            audio = (
                await transaction.get_audio_artifact(job.result_artifact_id)
                if job is not None and job.result_artifact_id is not None
                else None
            )
            bundle = (
                await transaction.get_export_bundle_artifact(job.result_artifact_id)
                if job is not None
                and job.result_artifact_id is not None
                and cursor.pending_steps[0] == "bundle"
                else None
            )
        if (
            job is None
            or job.run_id != cursor.media_run_id
            or job.project_id != cursor.project_id
            or job.status is not JobStatus.SUCCEEDED
            or job.result_artifact_id is None
        ):
            raise ApplicationError(
                "EXPORT_JOB_INCOMPLETE", "the pending export Job has not succeeded"
            )
        step = cursor.pending_steps[0]
        audio_ids = cursor.audio_artifact_ids
        bundle_id = cursor.bundle_artifact_id
        if step == "bundle":
            if (
                not isinstance(bundle, ExportBundleArtifact)
                or bundle.project_id != revision.project_id
                or bundle.revision_id != revision.revision_id
                or bundle.arrangement_hash != revision.content_hash
                or bundle.source_job_id != job_id
                or bundle.seed != cursor.seed
                or set(bundle.input_artifact_ids) != set(cursor.audio_artifact_ids)
            ):
                raise ApplicationError(
                    "EXPORT_ARTIFACT_LINEAGE_MISMATCH", "Bundle lineage does not match"
                )
            bundle_id = bundle.artifact_id
        else:
            if not isinstance(audio, AudioArtifact):
                raise ApplicationError(
                    "EXPORT_ARTIFACT_NOT_FOUND", "completed audio Artifact is missing"
                )
            if step == "master":
                profile = MediaQualityProfile.CANONICAL_MASTER_V1
                scope = RenderScope.MASTER
                track_ids: tuple[UUID, ...] = ()
            elif step.startswith("stem:"):
                profile = MediaQualityProfile.CANONICAL_STEM_V1
                scope = RenderScope.STEM
                track_ids = (_track_id_for_step(revision, step),)
            else:
                profile = MediaQualityProfile.DELIVERY_MP3_V1
                scope = RenderScope.MASTER
                track_ids = ()
            _verify_audio_lineage(
                audio,
                revision=revision,
                profile=profile,
                render_scope=scope,
                render_track_ids=track_ids,
                source_job_id=job_id,
            )
            audio_ids = (*audio_ids, audio.artifact_id)
        return cursor.model_copy(
            update={
                "pending_job_id": None,
                "pending_idempotency_key": None,
                "completed_steps": (*cursor.completed_steps, step),
                "completed_job_ids": (*cursor.completed_job_ids, job_id),
                "audio_artifact_ids": audio_ids,
                "bundle_artifact_id": bundle_id,
            }
        )


class PersistPlanningResultRequest(DomainModel):
    run_id: UUID
    expected_run_version: int = Field(ge=0)
    planning_result: PlanningResult
    style_pack_version: Literal["synth-ambient.v1"] = "synth-ambient.v1"


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
        plan_record = PersistedCompositionPlan(
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
        async with self._ai_run_uow_factory() as transaction:
            persisted, run = await transaction.persist_plan_and_mark_pending(
                plan=plan_record,
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
        return verify_loaded_plan_identity(
            persisted,
            expected_plan_hash=expected_plan_hash,
            require_compilation_safe=require_compilation_safe,
        )


def verify_loaded_plan_identity(
    persisted: PersistedCompositionPlan,
    *,
    expected_plan_hash: str,
    require_compilation_safe: bool = False,
) -> PersistedCompositionPlan:
    """Verify one persisted Plan identity before any consumer may compile it."""

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
    receipt_id: UUID | None = None


Compiler = Callable[..., CompositionBuild]


class MaterializeApprovedComposition:
    """Compile and materialize through the existing Preview transaction after authorization."""

    def __init__(
        self,
        materialization_uow_factory: CompositionMaterializationUnitOfWorkFactory,
        *,
        compiler: Compiler = compile_synth_ambient_plan,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._compiler = compiler
        self._materialization_uow_factory = materialization_uow_factory
        self._clock = clock

    async def __call__(
        self, request: MaterializeApprovedCompositionRequest
    ) -> MaterializeApprovedCompositionResult:
        fingerprint = request_hash(
            {
                "schema": "composition-materialization.v1",
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        now = self._clock()
        async with self._materialization_uow_factory() as transaction:
            run = await transaction.lock_ai_run(request.run_id)
            approval = await transaction.read_ai_run_approval(request.run_id)
            if approval is None:
                raise ApplicationError(
                    "AI_RUN_APPROVAL_REQUIRED", "materialization requires persisted approval"
                )
            self._verify_request_identity(request, run, approval)
            receipt = await transaction.read_materialization_receipt(
                run_id=request.run_id,
                plan_id=request.plan_id,
                plan_hash=request.expected_plan_hash,
                seed=request.seed,
            )
            if receipt is not None:
                if (
                    receipt.request_hash != fingerprint
                    or receipt.actor_id != request.actor_id
                    or receipt.assertion_hash != approval.assertion_hash
                    or receipt.run_id != request.run_id
                    or receipt.plan_id != request.plan_id
                    or receipt.plan_content_hash != request.expected_plan_hash
                    or receipt.seed != request.seed
                ):
                    raise ApplicationError(
                        "MATERIALIZATION_REQUEST_CONFLICT",
                        "this approved Plan was materialized by a different request",
                    )
                return MaterializeApprovedCompositionResult(
                    status="approved",
                    plan_id=receipt.plan_id,
                    candidate_snapshot_id=receipt.candidate_snapshot_id,
                    preview_id=receipt.preview_id,
                    revision_id=receipt.revision_id,
                    receipt_id=receipt.receipt_id,
                    replayed=True,
                )
            if approval.decision == "reject":
                if run.status is not AIRunStatus.REJECTED:
                    raise ApplicationError(
                        "AI_RUN_APPROVAL_CONFLICT", "the rejected decision is not authoritative"
                    )
                return MaterializeApprovedCompositionResult(
                    status="rejected", plan_id=request.plan_id
                )
            if run.status is not AIRunStatus.MATERIALIZING or approval.decision != "approve":
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
            if persisted.style_pack_version != "synth-ambient.v1":
                raise ApplicationError(
                    "PLAN_IDENTITY_MISMATCH", "the Plan or Style Pack identity is invalid"
                )
            if run.brief is None:
                raise ApplicationError("BRIEF_NOT_FOUND", "the authoritative Brief is missing")
            try:
                brief = CompositionBrief.model_validate_json(json.dumps(run.brief), strict=True)
            except ValueError as exc:
                raise ApplicationError(
                    "BRIEF_INVALID", "the authoritative composition Brief is invalid"
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
                f"{request.run_id}:{request.plan_id}:{request.seed}".encode()
            ).hexdigest()
            preview = await create_command_preview_in_transaction(
                transaction,
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
                ),
                id_factory=uuid4,
                now=now,
                preview_ttl=timedelta(hours=24),
                versions=VersionRefs(
                    policy="change-impact.v1",
                    audio_engine="motif-forge-audio-engine.v1",
                    graph="motif-forge-parent.v2",
                    prompt=persisted.prompt_version,
                    knowledge=persisted.style_pack_version,
                    assets="builtin-seed-palette.v1",
                    compiler=SYNTH_AMBIENT_COMPILER_VERSION,
                ),
            )
            decision = await approve_preview_in_transaction(
                transaction,
                DecidePreviewRequest(
                    preview_id=preview.preview_id,
                    decision=PreviewDecision.APPROVE,
                    actor_id=request.actor_id,
                    approval_assertion=request.approval_assertion,
                    idempotency_key=f"s2-approve:{key_digest}",
                ),
                id_factory=uuid4,
                now=now,
            )
            if isinstance(decision, RevisionConflictError):  # pragma: no cover - rollback policy
                raise decision
            if decision.revision_id is None:
                raise ApplicationError("MATERIALIZATION_FAILED", "Revision was not created")
            revision = await transaction.get_revision(decision.revision_id)
            if revision is None or revision.command_batch_id is None:
                raise ApplicationError("MATERIALIZATION_FAILED", "Revision receipt is incomplete")
            receipt = CompositionMaterializationReceipt(
                receipt_id=uuid4(),
                run_id=request.run_id,
                plan_id=request.plan_id,
                plan_content_hash=request.expected_plan_hash,
                plan_hash_version=persisted.hash_version,
                seed=request.seed,
                request_hash=fingerprint,
                actor_id=request.actor_id,
                assertion_hash=approval.assertion_hash,
                candidate_snapshot_id=preview.candidate_snapshot_id,
                preview_id=preview.preview_id,
                revision_id=decision.revision_id,
                command_batch_id=revision.command_batch_id,
                style_pack_version="synth-ambient.v1",
                compiler_version=SYNTH_AMBIENT_COMPILER_VERSION,
                created_at=now,
            )
            await transaction.insert_materialization_receipt(
                receipt,
                AIRunEvent(
                    sequence=1,
                    event_id=uuid4(),
                    run_id=request.run_id,
                    event_type="composition.materialized",
                    phase="materializing",
                    payload={
                        "receipt_id": str(receipt.receipt_id),
                        "receipt_schema_version": receipt.schema_version,
                        "plan_id": str(request.plan_id),
                        "plan_hash": request.expected_plan_hash,
                        "plan_hash_version": persisted.hash_version,
                        "seed": request.seed,
                        "candidate_snapshot_id": str(preview.candidate_snapshot_id),
                        "preview_id": str(preview.preview_id),
                        "revision_id": str(decision.revision_id),
                        "command_batch_id": str(revision.command_batch_id),
                        "style_pack_version": persisted.style_pack_version,
                        "compiler_version": SYNTH_AMBIENT_COMPILER_VERSION,
                    },
                    dedupe_key=f"materialized:{request.plan_id}:{request.seed}",
                    created_at=now,
                ),
            )
            return MaterializeApprovedCompositionResult(
                status="approved",
                plan_id=request.plan_id,
                candidate_snapshot_id=preview.candidate_snapshot_id,
                preview_id=preview.preview_id,
                revision_id=decision.revision_id,
                receipt_id=receipt.receipt_id,
            )

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
