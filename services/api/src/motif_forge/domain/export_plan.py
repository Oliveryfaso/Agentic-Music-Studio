"""Pure plan-bound v2 export contracts, alongside unchanged legacy v1 consumers."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.ir import (
    ArrangementIR,
    ArrangementIRV2,
    ArrangementIRV3,
    ArrangementIRV4,
    ArrangementIRV5,
    DomainModel,
    EnsemblePianoRenderProfile,
    EqPianoRenderProfile,
    MixPianoRenderProfile,
    NoteClip,
    PianoRenderProfile,
    TrackType,
)

if TYPE_CHECKING:
    from motif_forge.domain.media_jobs import MediaQualityProfile
    from motif_forge.domain.revisions import Revision


def _sorted_ids(ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
    return tuple(sorted(ids, key=str))


def verify_v1_export_source(arrangement: ArrangementIR) -> None:
    """This preparation has no approved external-asset credits/pack reader yet."""
    if isinstance(arrangement, ArrangementIRV2):
        raise ValueError("EXPORT_SOURCE_PROFILE_UNSUPPORTED")
    if any(
        track.track_type is not TrackType.INSTRUMENT
        or not (track.instrument_ref or "").startswith("builtin:")
        or any(not isinstance(clip, NoteClip) for clip in track.clips)
        for track in arrangement.tracks
    ):
        raise ValueError("EXPORT_SOURCE_PROFILE_UNSUPPORTED")


class ExportPlanV2(DomainModel):
    schema_version: Literal["export-plan.v2"] = "export-plan.v2"
    project_id: UUID
    revision_id: UUID
    arrangement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0, le=2**31 - 1)
    track_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    stem_track_ids: tuple[UUID, ...] = Field(default=(), max_length=12)
    include_mp3: bool = True
    request_id: UUID | None = None
    engine_version: Literal["motif-forge-audio-engine.v1"] = "motif-forge-audio-engine.v1"

    @model_serializer(mode="wrap")
    def serialize_plan(self, handler: SerializerFunctionWrapHandler):  # type: ignore[no-untyped-def]
        # No return annotation: retain the model field schema for OpenAPI responses.
        value: dict[str, Any] = handler(self)
        if self.request_id is None:
            value.pop("request_id", None)
        return value

    @model_validator(mode="after")
    def validate_tracks(self) -> Self:
        if (
            len(set(self.track_ids)) != len(self.track_ids)
            or self.track_ids != _sorted_ids(self.track_ids)
            or len(set(self.stem_track_ids)) != len(self.stem_track_ids)
            or self.stem_track_ids != _sorted_ids(self.stem_track_ids)
        ):
            raise ValueError("EXPORT_TRACK_IDS_NOT_CANONICAL")
        if not set(self.stem_track_ids).issubset(self.track_ids):
            raise ValueError("EXPORT_TRACK_NOT_IN_REVISION")
        return self

    @property
    def steps(self) -> tuple[str, ...]:
        return (
            "master",
            *(f"stem:{track}" for track in self.stem_track_ids),
            *(("mp3",) if self.include_mp3 else ()),
            "bundle",
        )

    @property
    def audio_files(self) -> tuple[tuple[str, MediaQualityProfile], ...]:
        # The Job module consumes this plan too; resolve its enum after imports finish.
        from motif_forge.domain.media_jobs import MediaQualityProfile

        return (
            ("master.wav", MediaQualityProfile.CANONICAL_MASTER_V1),
            *(
                (f"stem-{track}.wav", MediaQualityProfile.CANONICAL_STEM_V1)
                for track in self.stem_track_ids
            ),
            *((("master.mp3", MediaQualityProfile.DELIVERY_MP3_V1),) if self.include_mp3 else ()),
        )

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


class PianoExportPlanV3(ExportPlanV2):
    schema_version: Literal["export-plan.v3"] = "export-plan.v3"  # type: ignore[assignment]
    engine_version: Literal["motif-forge-audio-engine.v2"] = "motif-forge-audio-engine.v2"  # type: ignore[assignment]
    render_profile: PianoRenderProfile


class EnsembleExportPlanV4(PianoExportPlanV3):
    schema_version: Literal["export-plan.v4"] = "export-plan.v4"  # type: ignore[assignment]
    engine_version: Literal["motif-forge-audio-engine.v3"] = "motif-forge-audio-engine.v3"  # type: ignore[assignment]
    render_profile: EnsemblePianoRenderProfile


class MixExportPlanV5(EnsembleExportPlanV4):
    schema_version: Literal["export-plan.v5"] = "export-plan.v5"  # type: ignore[assignment]
    engine_version: Literal["motif-forge-audio-engine.v4"] = "motif-forge-audio-engine.v4"  # type: ignore[assignment]
    render_profile: MixPianoRenderProfile


class EqExportPlanV6(MixExportPlanV5):
    schema_version: Literal["export-plan.v6"] = "export-plan.v6"  # type: ignore[assignment]
    engine_version: Literal["motif-forge-audio-engine.v5"] = "motif-forge-audio-engine.v5"  # type: ignore[assignment]
    render_profile: EqPianoRenderProfile


ExportPlanValue = Annotated[
    ExportPlanV2 | PianoExportPlanV3 | EnsembleExportPlanV4 | MixExportPlanV5 | EqExportPlanV6,
    Field(discriminator="schema_version"),
]


def read_export_plan_json(
    value: str | bytes, *, strict: Literal[True] = True
) -> ExportPlanV2 | PianoExportPlanV3 | EnsembleExportPlanV4 | MixExportPlanV5 | EqExportPlanV6:
    data = json.loads(value)
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version == "export-plan.v2":
        return ExportPlanV2.model_validate_json(value, strict=strict)
    if version == "export-plan.v3":
        return PianoExportPlanV3.model_validate_json(value, strict=strict)
    if version == "export-plan.v4":
        return EnsembleExportPlanV4.model_validate_json(value, strict=strict)
    if version == "export-plan.v5":
        return MixExportPlanV5.model_validate_json(value, strict=strict)
    if version == "export-plan.v6":
        return EqExportPlanV6.model_validate_json(value, strict=strict)
    raise ValueError("EXPORT_PLAN_VERSION_UNSUPPORTED")


def verify_export_plan_revision(plan: ExportPlanValue, revision: Revision) -> None:
    if isinstance(plan, PianoExportPlanV3):
        if (
            not isinstance(revision.arrangement_ir, ArrangementIRV2)
            or plan.render_profile != revision.arrangement_ir.render_profile
        ):
            raise ValueError("EXPORT_SOURCE_PROFILE_UNSUPPORTED")
    else:
        verify_v1_export_source(revision.arrangement_ir)
    if (
        revision.project_id != plan.project_id
        or revision.revision_id != plan.revision_id
        or revision.content_hash != plan.arrangement_hash
        or arrangement_content_hash(revision.arrangement_ir) != plan.arrangement_hash
        or _sorted_ids(tuple(t.track_id for t in revision.arrangement_ir.tracks)) != plan.track_ids
    ):
        raise ValueError("EXPORT_PLAN_REVISION_MISMATCH")


def plan_export(
    revision: Revision,
    *,
    seed: int,
    include_mp3: bool = True,
    stem_track_ids: tuple[UUID, ...] = (),
    request_id: UUID | None = None,
) -> ExportPlanValue:
    values: dict[str, Any] = dict(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        arrangement_hash=revision.content_hash,
        seed=seed,
        track_ids=_sorted_ids(tuple(t.track_id for t in revision.arrangement_ir.tracks)),
        stem_track_ids=_sorted_ids(stem_track_ids),
        include_mp3=include_mp3,
        request_id=request_id,
    )
    plan = (
        EqExportPlanV6(**values, render_profile=revision.arrangement_ir.render_profile)
        if isinstance(revision.arrangement_ir, ArrangementIRV5)
        else MixExportPlanV5(**values, render_profile=revision.arrangement_ir.render_profile)
        if isinstance(revision.arrangement_ir, ArrangementIRV4)
        else EnsembleExportPlanV4(**values, render_profile=revision.arrangement_ir.render_profile)
        if isinstance(revision.arrangement_ir, ArrangementIRV3)
        else PianoExportPlanV3(**values, render_profile=revision.arrangement_ir.render_profile)
        if isinstance(revision.arrangement_ir, ArrangementIRV2)
        else ExportPlanV2(**values)
    )
    verify_export_plan_revision(plan, revision)
    return plan


def export_key_v2(plan: ExportPlanValue, step: str) -> str:
    if step not in plan.steps:
        raise ValueError("EXPORT_STEP_NOT_IN_PLAN")
    version = plan.schema_version.rsplit(".", 1)[1]
    digest = hashlib.sha256(
        f"complete-export.{version}:{plan.content_hash}:{step}".encode()
    ).hexdigest()
    return f"complete-export:{version}:{digest}"


class CompleteExportCursorV2(DomainModel):
    schema_version: Literal["complete-export-cursor.v2"] = "complete-export-cursor.v2"
    plan: ExportPlanValue
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    thread_id: str = Field(min_length=1, max_length=160)
    run_type: Literal["complete_song_export.v2", "parent.export.v1"] = "complete_song_export.v2"
    media_run_id: UUID | None = None
    pending_job_id: UUID | None = None
    pending_idempotency_key: str | None = Field(default=None, max_length=160)
    completed_steps: tuple[str, ...] = ()
    completed_job_ids: tuple[UUID, ...] = ()
    audio_artifact_ids: tuple[UUID, ...] = ()
    bundle_artifact_id: UUID | None = None

    @model_serializer(mode="wrap")
    def serialize_cursor(self, handler: SerializerFunctionWrapHandler):  # type: ignore[no-untyped-def]
        # No return annotation: retain the model field schema for OpenAPI responses.
        value: dict[str, Any] = handler(self)
        if self.run_type == "complete_song_export.v2":
            value.pop("run_type", None)
        return value

    @model_validator(mode="after")
    def validate_progress(self) -> Self:
        if self.plan_hash != self.plan.content_hash:
            raise ValueError("EXPORT_PLAN_HASH_MISMATCH")
        count = len(self.completed_steps)
        if self.completed_steps != self.plan.steps[:count]:
            raise ValueError("completed_steps must be an ordered export prefix")
        if len(self.completed_job_ids) != count or len(self.audio_artifact_ids) != min(
            count, len(self.plan.steps) - 1
        ):
            raise ValueError("EXPORT_PROGRESS_COUNT_INVALID")
        if len(set(self.completed_job_ids)) != count or len(set(self.audio_artifact_ids)) != len(
            self.audio_artifact_ids
        ):
            raise ValueError("EXPORT_PROGRESS_IDENTITIES_INVALID")
        finished = count == len(self.plan.steps)
        if (
            finished != (self.bundle_artifact_id is not None)
            or self.bundle_artifact_id in self.audio_artifact_ids
        ):
            raise ValueError("EXPORT_BUNDLE_PROGRESS_INVALID")
        if (self.pending_job_id is None) != (self.pending_idempotency_key is None):
            raise ValueError("EXPORT_PENDING_IDENTITY_INCOMPLETE")
        if self.pending_job_id is not None and (
            finished
            or self.pending_job_id in self.completed_job_ids
            or self.pending_idempotency_key != export_key_v2(self.plan, self.plan.steps[count])
        ):
            raise ValueError("EXPORT_PENDING_IDENTITY_INVALID")
        if (count > 0 or self.pending_job_id is not None) != (self.media_run_id is not None):
            raise ValueError("EXPORT_RUN_IDENTITY_INVALID")
        return self

    @property
    def project_id(self) -> UUID:
        return self.plan.project_id

    @property
    def revision_id(self) -> UUID:
        return self.plan.revision_id

    @property
    def seed(self) -> int:
        return self.plan.seed

    @property
    def pending_steps(self) -> tuple[str, ...]:
        return self.plan.steps[len(self.completed_steps) :]
