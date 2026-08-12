"""Deterministically materialize one validated import Artifact into a Revision."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field

from motif_forge.application.errors import ApplicationError
from motif_forge.application.ports import MediaJobUnitOfWorkFactory, UnitOfWorkFactory
from motif_forge.application.revisions import (
    CommitCommandBatch,
    CommitCommandBatchRequest,
    CommitCommandBatchResult,
)
from motif_forge.domain.commands import ImportAudioCommand, ImportAudioPayload
from motif_forge.domain.ir import DomainModel, TimeStretchRef
from motif_forge.domain.media_jobs import (
    ArtifactAvailability,
    ArtifactValidationStatus,
    FeatureProfile,
    ImportedAudioAnalysis,
    MediaQualityProfile,
)
from motif_forge.domain.revisions import AuthorKind
from motif_forge.domain.timebase import seconds_to_ticks


class MaterializeImportRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    normalized_artifact_id: UUID
    original_normalized_artifact_id: UUID | None = None
    source_bpm: float | None = Field(default=None, ge=30.0, le=300.0)
    target_bpm: float | None = Field(default=None, ge=30.0, le=300.0)
    track_name: str = Field(default="Imported Audio", min_length=1, max_length=80)


class ImportAnalysisContext(DomainModel):
    normalized_artifact_id: UUID
    duration_seconds: float = Field(gt=0.0, le=1800.0)
    project_bpm: float = Field(ge=30.0, le=300.0)
    analysis: ImportedAudioAnalysis


class LoadImportAnalysisContext:
    def __init__(
        self, project_uow: UnitOfWorkFactory, media_uow: MediaJobUnitOfWorkFactory
    ) -> None:
        self._project_uow = project_uow
        self._media_uow = media_uow

    async def __call__(
        self, *, project_id: UUID, base_revision_id: UUID, normalized_artifact_id: UUID
    ) -> ImportAnalysisContext:
        async with self._media_uow() as transaction:
            artifact = await transaction.get_audio_artifact(normalized_artifact_id)
            analysis_feature = await transaction.get_feature_artifact_for_source(
                normalized_artifact_id, FeatureProfile.IMPORT_ANALYSIS_V1
            )
        if (
            artifact is None
            or artifact.project_id != project_id
            or artifact.media_role != "normalized_import_audio"
            or artifact.duration_seconds is None
            or artifact.analysis is None
            or analysis_feature is None
            or analysis_feature.availability is not ArtifactAvailability.AVAILABLE
        ):
            raise ApplicationError(
                "IMPORT_ANALYSIS_UNAVAILABLE",
                "normalized import analysis is unavailable or invalid",
            )
        async with self._project_uow() as transaction:
            revision = await transaction.get_revision(base_revision_id)
        if revision is None or revision.project_id != project_id:
            raise ApplicationError("REVISION_NOT_FOUND", "base import revision does not exist")
        return ImportAnalysisContext(
            normalized_artifact_id=normalized_artifact_id,
            duration_seconds=artifact.duration_seconds,
            project_bpm=revision.arrangement_ir.tempo_map[0].bpm,
            analysis=artifact.analysis,
        )


class MaterializeImport:
    def __init__(
        self,
        project_uow: UnitOfWorkFactory,
        media_uow: MediaJobUnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._project_uow = project_uow
        self._media_uow = media_uow
        self._id_factory = id_factory

    async def __call__(self, request: MaterializeImportRequest) -> CommitCommandBatchResult:
        async with self._media_uow() as transaction:
            artifact = await transaction.get_audio_artifact(request.normalized_artifact_id)
        if (
            artifact is None
            or artifact.project_id != request.project_id
            or artifact.quality_profile is not MediaQualityProfile.WORKING_PCM_V1
            or artifact.validation_status is not ArtifactValidationStatus.VALIDATED
            or artifact.availability is not ArtifactAvailability.AVAILABLE
            or artifact.duration_seconds is None
        ):
            raise ApplicationError(
                "IMPORT_ARTIFACT_INVALID",
                "import materialization requires an available validated working PCM Artifact",
            )
        async with self._project_uow() as transaction:
            base_revision = await transaction.get_revision(request.base_revision_id)
        if base_revision is None or base_revision.project_id != request.project_id:
            raise ApplicationError(
                "REVISION_NOT_FOUND", "base revision for import materialization does not exist"
            )
        tempo = Decimal(str(base_revision.arrangement_ir.tempo_map[0].bpm))
        duration_tick = seconds_to_ticks(Decimal(str(artifact.duration_seconds)), bpm=tempo)
        stable_id = uuid5(NAMESPACE_URL, f"motif-forge:import:{artifact.artifact_id}")
        command = ImportAudioCommand(
            command_id=stable_id,
            actor_kind="system",
            client_sequence=0,
            payload=ImportAudioPayload(
                track_id=uuid5(stable_id, "track"),
                clip_id=uuid5(stable_id, "clip"),
                section_id=uuid5(stable_id, "section"),
                artifact_id=artifact.artifact_id,
                track_name=request.track_name,
                duration_tick=duration_tick,
                source_duration_seconds=artifact.duration_seconds,
                source_bpm=request.source_bpm,
                target_bpm=request.target_bpm,
                time_stretch_ref=(
                    TimeStretchRef(
                        artifact_id=artifact.artifact_id,
                        source_artifact_id=request.original_normalized_artifact_id,
                        preserve_pitch=True,
                        ratio=request.target_bpm / request.source_bpm,
                        source_bpm=request.source_bpm,
                        target_bpm=request.target_bpm,
                        engine_version=artifact.encoder_version,
                    )
                    if request.original_normalized_artifact_id is not None
                    and request.source_bpm is not None
                    and request.target_bpm is not None
                    else None
                ),
            ),
        )
        return await CommitCommandBatch(self._project_uow, id_factory=self._id_factory)(
            CommitCommandBatchRequest(
                project_id=request.project_id,
                branch_id=request.branch_id,
                base_revision_id=request.base_revision_id,
                commands=(command,),
                actor_id="media-import-worker",
                author_kind=AuthorKind.SYSTEM,
                reason="AUDIO_IMPORT_MATERIALIZED",
                idempotency_key=f"import:{artifact.artifact_id}",
            )
        )
