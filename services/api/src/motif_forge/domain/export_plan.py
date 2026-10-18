"""Pure v2 export contracts. Production activation requires the PostgreSQL gate."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.ir import ArrangementIR, DomainModel, NoteClip, TrackType

if TYPE_CHECKING:
    from motif_forge.domain.media_jobs import MediaQualityProfile
    from motif_forge.domain.revisions import Revision


def _sorted_ids(ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
    return tuple(sorted(ids, key=str))


def verify_v1_export_source(arrangement: ArrangementIR) -> None:
    """This preparation has no approved external-asset credits/pack reader yet."""
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
    engine_version: Literal["motif-forge-audio-engine.v1"] = "motif-forge-audio-engine.v1"

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


def verify_export_plan_revision(plan: ExportPlanV2, revision: Revision) -> None:
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
) -> ExportPlanV2:
    plan = ExportPlanV2(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        arrangement_hash=revision.content_hash,
        seed=seed,
        track_ids=_sorted_ids(tuple(t.track_id for t in revision.arrangement_ir.tracks)),
        stem_track_ids=_sorted_ids(stem_track_ids),
        include_mp3=include_mp3,
    )
    verify_export_plan_revision(plan, revision)
    return plan


def export_key_v2(plan: ExportPlanV2, step: str) -> str:
    if step not in plan.steps:
        raise ValueError("EXPORT_STEP_NOT_IN_PLAN")
    digest = hashlib.sha256(f"complete-export.v2:{plan.content_hash}:{step}".encode()).hexdigest()
    return f"complete-export:v2:{digest}"


class CompleteExportCursorV2(DomainModel):
    schema_version: Literal["complete-export-cursor.v2"] = "complete-export-cursor.v2"
    plan: ExportPlanV2
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    thread_id: str = Field(min_length=1, max_length=160)
    media_run_id: UUID | None = None
    pending_job_id: UUID | None = None
    pending_idempotency_key: str | None = Field(default=None, max_length=160)
    completed_steps: tuple[str, ...] = ()
    completed_job_ids: tuple[UUID, ...] = ()
    audio_artifact_ids: tuple[UUID, ...] = ()
    bundle_artifact_id: UUID | None = None

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
    def pending_steps(self) -> tuple[str, ...]:
        return self.plan.steps[len(self.completed_steps) :]
