"""PostgreSQL-backed S7 Export read projection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from motif_forge.application.export_reads import (
    ExportBundleSummary,
    ExportFileSummary,
    ExportStepSummary,
    RevisionExportProjection,
    StoredExportBundle,
    _manifest_member,
)
from motif_forge.application.generation import EXPORT_STEPS
from motif_forge.domain.export_plan import (
    EnsembleExportPlanV4,
    ExportPlanValue,
    MixExportPlanV5,
    PianoExportPlanV3,
    export_key_v2,
    read_export_plan_json,
    verify_export_plan_revision,
)
from motif_forge.domain.media_jobs import ArtifactAvailability, MediaQualityProfile
from motif_forge.infrastructure.persistence.database import SessionFactory, _revision_from_row
from motif_forge.infrastructure.persistence.tables import (
    AudioArtifactRow,
    ExportBundleArtifactRow,
    MediaJobRow,
    MediaRunRow,
    RevisionRow,
)


class PostgresExportProjectionStore:
    def __init__(self, session_factory: SessionFactory, *, artifact_root: Path) -> None:
        self._session_factory = session_factory
        self._artifact_root = artifact_root.resolve()

    async def read_revision_export(
        self, *, project_id: UUID, revision_id: UUID, plan_hash: str | None = None
    ) -> RevisionExportProjection | None:
        async with self._session_factory() as session:
            revision = (
                await session.execute(
                    select(RevisionRow).where(
                        RevisionRow.id == revision_id, RevisionRow.project_id == project_id
                    )
                )
            ).scalar_one_or_none()
            if revision is None:
                return None
            all_jobs = tuple(
                (
                    await session.execute(
                        select(MediaJobRow)
                        .where(MediaJobRow.project_id == project_id)
                        .order_by(MediaJobRow.created_at, MediaJobRow.id)
                    )
                ).scalars()
            )
            jobs = tuple(
                row
                for row in all_jobs
                if (
                    row.input_payload.get("revision_id") == str(revision_id)
                    or (
                        row.input_payload.get("schema_version") == "export-bundle-job.v2"
                        and isinstance(row.input_payload.get("plan"), dict)
                        and row.input_payload["plan"].get("revision_id") == str(revision_id)
                    )
                )
            )
            artifacts = tuple(
                (
                    await session.execute(
                        select(AudioArtifactRow)
                        .where(
                            AudioArtifactRow.project_id == project_id,
                            AudioArtifactRow.revision_id == revision_id,
                        )
                        .order_by(AudioArtifactRow.created_at, AudioArtifactRow.id)
                    )
                ).scalars()
            )
            runs = (
                tuple(
                    (
                        await session.execute(
                            select(MediaRunRow)
                            .where(
                                MediaRunRow.id.in_({item.run_id for item in jobs}),
                                MediaRunRow.run_type.in_(
                                    (
                                        "complete_song_export.v1",
                                        "complete_song_export.v2",
                                        "parent.export.v1",
                                    )
                                ),
                            )
                            .order_by(MediaRunRow.created_at, MediaRunRow.id)
                        )
                    ).scalars()
                )
                if jobs
                else ()
            )
            if plan_hash is not None:
                selected = tuple(run for run in runs if run.plan_hash == plan_hash)
                if not selected:
                    return None
            else:
                legacy = tuple(run for run in runs if run.plan_hash is None)
                selected = legacy if legacy else runs[-1:]
            media_runs = {run.id: run for run in selected}
            jobs = tuple(job for job in jobs if job.run_id in media_runs)
            job_ids = {job.id for job in jobs}
            artifacts = tuple(
                artifact for artifact in artifacts if artifact.source_job_id in job_ids
            )
            selected_hash = selected[0].plan_hash if selected else None
            bundle_query = select(ExportBundleArtifactRow).where(
                ExportBundleArtifactRow.project_id == project_id,
                ExportBundleArtifactRow.revision_id == revision_id,
                ExportBundleArtifactRow.plan_hash == selected_hash,
            )
            bundle_row = (await session.execute(bundle_query)).scalar_one_or_none()

        return self._project(
            revision=revision,
            jobs=jobs,
            artifacts=artifacts,
            bundle_row=bundle_row,
            media_runs=media_runs,
        )

    async def read_bundle(self, bundle_id: UUID) -> StoredExportBundle | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(ExportBundleArtifactRow).where(ExportBundleArtifactRow.id == bundle_id)
                )
            ).scalar_one_or_none()
        return _stored_bundle(row) if row is not None else None

    def _project(
        self,
        *,
        revision: RevisionRow,
        jobs: tuple[MediaJobRow, ...],
        artifacts: tuple[AudioArtifactRow, ...],
        bundle_row: ExportBundleArtifactRow | None,
        media_runs: dict[UUID, MediaRunRow],
    ) -> RevisionExportProjection:
        plan: ExportPlanValue | None = None
        plan_error: str | None = None
        try:
            if len(media_runs) == 1:
                run = next(iter(media_runs.values()))
                if run.schema_version == "media-run.v2":
                    plan = read_export_plan_json(json.dumps(run.export_plan), strict=True)
                    if run.plan_hash != plan.content_hash:
                        raise ValueError("plan pin mismatch")
                    verify_export_plan_revision(plan, _revision_from_row(revision))
            if (
                bundle_row is not None
                and bundle_row.schema_version
                in {
                    "export-bundle-artifact.v2",
                    "export-bundle-artifact.v3",
                    "export-bundle-artifact.v4",
                    "export-bundle-artifact.v5",
                }
                and plan is None
            ):
                raise ValueError("v2 bundle has no v2 Run")
        except (ValueError, TypeError, KeyError):
            plan_error = "EXPORT_PLAN_INVALID"
        expected_steps = plan.steps if plan is not None else EXPORT_STEPS
        lineage_error = plan_error or (
            _lineage_error_v2(jobs, artifacts, bundle_row, media_runs, plan)
            if plan is not None
            else _lineage_error(jobs, artifacts, bundle_row, media_runs)
        )
        steps = tuple(
            ExportStepSummary(
                step=step,
                job_id=(jobs[index].id if index < len(jobs) else None),
                status=(jobs[index].status if index < len(jobs) else "pending"),
                artifact_id=(jobs[index].result_artifact_id if index < len(jobs) else None),
                error_code=(jobs[index].error_code if index < len(jobs) else None),
            )
            for index, step in enumerate(expected_steps)
        )
        bundle = _public_bundle(bundle_row) if bundle_row is not None else None
        files: tuple[ExportFileSummary, ...] = ()
        manifest_error: str | None = None
        if lineage_error is None:
            try:
                files = self._files(artifacts=artifacts, bundle=bundle_row)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                manifest_error = "EXPORT_MANIFEST_INVALID"
        error_code = (
            lineage_error
            or manifest_error
            or next((item.error_code for item in steps if item.error_code), None)
        )
        if any(run.status == "cancelled" for run in media_runs.values()):
            status = "cancelled"
        elif error_code is not None:
            status = "failed"
        elif (
            bundle is not None
            and bundle.availability is ArtifactAvailability.AVAILABLE
            and len(jobs) == len(expected_steps)
            and all(item.status == "succeeded" for item in steps)
            and (
                plan is None
                or all(item.availability is ArtifactAvailability.AVAILABLE for item in files)
            )
        ):
            status = "ready"
        else:
            status = "partial"
        return RevisionExportProjection(
            project_id=revision.project_id,
            revision_id=revision.id,
            source_run_id=revision.source_run_id,
            export_thread_id=next(iter(media_runs.values())).thread_id
            if plan is not None
            else None,
            export_plan=plan,
            plan_hash=plan.content_hash if plan is not None else None,
            status=status,
            bundle=bundle,
            steps=steps,
            files=files,
            error_code=error_code,
        )

    def _files(
        self,
        *,
        artifacts: tuple[AudioArtifactRow, ...],
        bundle: ExportBundleArtifactRow | None,
    ) -> tuple[ExportFileSummary, ...]:
        if bundle is None:
            return tuple(_audio_file(item, filename=_audio_filename(item)) for item in artifacts)
        directory = (self._artifact_root / bundle.storage_prefix).resolve()
        if not directory.is_relative_to(self._artifact_root):
            raise ValueError("bundle outside root")
        manifest_path = directory / "export-manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("manifest is symlink")
        raw = manifest_path.read_bytes()
        if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != bundle.content_hash:
            raise ValueError("manifest pin mismatch")
        manifest = json.loads(raw)
        version = (
            "export-manifest.v2"
            if bundle.schema_version
            in {
                "export-bundle-artifact.v2",
                "export-bundle-artifact.v3",
                "export-bundle-artifact.v4",
                "export-bundle-artifact.v5",
            }
            else "export-manifest.v1"
        )
        if (
            manifest.get("schema_version") != version
            or manifest.get("project_id") != str(bundle.project_id)
            or manifest.get("revision_id") != str(bundle.revision_id)
            or not isinstance(manifest.get("files"), list)
        ):
            raise ValueError("manifest invalid")
        artifact_by_id = {str(item.id): item for item in artifacts}
        values: list[ExportFileSummary] = []
        for entry in manifest["files"]:
            if not isinstance(entry, dict):
                raise ValueError("manifest entry invalid")
            filename = entry["filename"]
            _manifest_member(manifest, bundle=_stored_bundle(bundle), filename=filename)
            checksum = entry["sha256"]
            byte_size = entry["bytes"]
            artifact_id = entry.get("artifact_id")
            if artifact_id is not None:
                artifact = artifact_by_id.get(artifact_id)
                if (
                    artifact is None
                    or artifact.content_hash != checksum
                    or artifact.byte_size != byte_size
                    or entry.get("quality_profile") != artifact.quality_profile
                    or entry.get("storage_key") != artifact.storage_key
                ):
                    raise ValueError("manifest Artifact missing or changed")
                values.append(_audio_file(artifact, filename=filename))
            else:
                values.append(
                    ExportFileSummary(
                        file_id=f"bundle:{bundle.id}:{filename}",
                        filename=filename,
                        category=_bundle_category(filename),
                        media_type=_media_type(filename),
                        byte_size=byte_size,
                        availability=ArtifactAvailability(bundle.availability),
                        checksum=checksum,
                        content_url=f"/api/v1/export-bundles/{bundle.id}/files/{filename}",
                    )
                )
        manifest_size = manifest_path.stat().st_size
        values.append(
            ExportFileSummary(
                file_id=f"bundle:{bundle.id}:export-manifest.json",
                filename="export-manifest.json",
                category="manifest",
                media_type="application/json",
                byte_size=manifest_size,
                availability=ArtifactAvailability(bundle.availability),
                checksum=bundle.content_hash,
                content_url=f"/api/v1/export-bundles/{bundle.id}/files/export-manifest.json",
            )
        )
        return tuple(values)


def _lineage_error(
    jobs: tuple[MediaJobRow, ...],
    artifacts: tuple[AudioArtifactRow, ...],
    bundle: ExportBundleArtifactRow | None,
    media_runs: dict[UUID, MediaRunRow],
) -> str | None:
    run_ids = {item.run_id for item in jobs}
    job_ids = {item.id for item in jobs}
    if len(jobs) > len(EXPORT_STEPS) or len(run_ids) > 1:
        return "EXPORT_LINEAGE_INVALID"
    if jobs and (
        len(media_runs) != 1
        or next(iter(media_runs.values())).run_type != "complete_song_export.v1"
    ):
        return "EXPORT_LINEAGE_INVALID"
    if any(item.source_job_id not in job_ids for item in artifacts):
        return "EXPORT_LINEAGE_INVALID"
    if bundle is not None and bundle.source_job_id not in job_ids:
        return "EXPORT_LINEAGE_INVALID"
    return None


def _lineage_error_v2(
    jobs: tuple[MediaJobRow, ...],
    artifacts: tuple[AudioArtifactRow, ...],
    bundle: ExportBundleArtifactRow | None,
    media_runs: dict[UUID, MediaRunRow],
    plan: ExportPlanValue,
) -> str | None:
    if len(media_runs) != 1 or len(jobs) > len(plan.steps):
        return "EXPORT_LINEAGE_INVALID"
    run = next(iter(media_runs.values()))
    if (
        run.run_type not in {"complete_song_export.v2", "parent.export.v1"}
        or run.plan_hash != plan.content_hash
    ):
        return "EXPORT_LINEAGE_INVALID"
    for step, job in zip(plan.steps, jobs, strict=False):
        expected_type = (
            "export_bundle"
            if step == "bundle"
            else "transcode_export"
            if step == "mp3"
            else "render_canonical"
        )
        if (
            job.run_id != run.id
            or job.idempotency_key != export_key_v2(plan, step)
            or job.job_type != expected_type
        ):
            return "EXPORT_LINEAGE_INVALID"
    by_job = {job.id: index for index, job in enumerate(jobs)}
    for artifact in artifacts:
        index = by_job.get(artifact.source_job_id) if artifact.source_job_id is not None else None
        if index is None or index >= len(plan.audio_files):
            return "EXPORT_LINEAGE_INVALID"
        step = plan.steps[index]
        expected_tracks = [step[5:]] if step.startswith("stem:") else []
        if (
            (
                isinstance(plan, PianoExportPlanV3)
                and step != "mp3"
                and artifact.encoder_version != plan.engine_version
            )
            or artifact.quality_profile != plan.audio_files[index][1].value
            or artifact.arrangement_hash != plan.arrangement_hash
            or artifact.render_track_ids != expected_tracks
            or artifact.render_scope != ("stem" if expected_tracks else "master")
        ):
            return "EXPORT_LINEAGE_INVALID"
    if bundle is not None and (
        len(jobs) != len(plan.steps)
        or bundle.source_job_id != jobs[-1].id
        or bundle.schema_version
        != (
            "export-bundle-artifact.v5"
            if isinstance(plan, MixExportPlanV5)
            else "export-bundle-artifact.v4"
            if isinstance(plan, EnsembleExportPlanV4)
            else "export-bundle-artifact.v3"
            if isinstance(plan, PianoExportPlanV3)
            else "export-bundle-artifact.v2"
        )
        or bundle.plan_hash != plan.content_hash
        or set(bundle.input_artifact_ids) != {str(a.id) for a in artifacts}
    ):
        return "EXPORT_LINEAGE_INVALID"
    return None


def _public_bundle(row: ExportBundleArtifactRow) -> ExportBundleSummary:
    return ExportBundleSummary(
        bundle_id=row.id,
        project_id=row.project_id,
        revision_id=row.revision_id,
        availability=ArtifactAvailability(row.availability),
        content_hash=row.content_hash,
        byte_size=row.byte_size,
        file_count=row.file_count,
        export_plan=read_export_plan_json(json.dumps(row.export_plan), strict=True)
        if row.schema_version
        in {
            "export-bundle-artifact.v2",
            "export-bundle-artifact.v3",
            "export-bundle-artifact.v4",
            "export-bundle-artifact.v5",
        }
        else None,
        plan_hash=row.plan_hash,
    )


def _stored_bundle(row: ExportBundleArtifactRow) -> StoredExportBundle:
    return StoredExportBundle(
        **_public_bundle(row).model_dump(mode="python"), storage_prefix=row.storage_prefix
    )


def _audio_filename(row: AudioArtifactRow) -> str:
    profile = MediaQualityProfile(row.quality_profile)
    if profile is MediaQualityProfile.CANONICAL_MASTER_V1:
        return "master.wav"
    if profile is MediaQualityProfile.DELIVERY_MP3_V1:
        return "master.mp3"
    if profile is MediaQualityProfile.CANONICAL_STEM_V1:
        arrangement_track = row.render_track_ids[0] if row.render_track_ids else str(row.id)
        return f"stem-{arrangement_track}.wav"
    return f"artifact-{row.id}.{row.container}"


def _audio_file(row: AudioArtifactRow, *, filename: str) -> ExportFileSummary:
    profile = MediaQualityProfile(row.quality_profile)
    category = (
        "master"
        if profile is MediaQualityProfile.CANONICAL_MASTER_V1
        else "delivery"
        if profile is MediaQualityProfile.DELIVERY_MP3_V1
        else "stem"
    )
    return ExportFileSummary(
        file_id=f"audio:{row.id}",
        filename=filename,
        category=category,
        media_type=_media_type(filename),
        byte_size=row.byte_size,
        availability=ArtifactAvailability(row.availability),
        checksum=row.content_hash,
        content_url=f"/api/v1/audio-artifacts/{row.id}/content",
        artifact_id=row.id,
    )


def _bundle_category(filename: str) -> str:
    if filename == "composition.mid":
        return "midi"
    if filename == "project.json":
        return "project"
    return "manifest"


def _media_type(filename: str) -> str:
    return {
        ".json": "application/json",
        ".mid": "audio/midi",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
    }.get(Path(filename).suffix.lower(), "application/octet-stream")
