"""PostgreSQL-backed S7 Export read projection."""

from __future__ import annotations

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
)
from motif_forge.application.generation import EXPORT_STEPS
from motif_forge.domain.media_jobs import ArtifactAvailability, MediaQualityProfile
from motif_forge.infrastructure.persistence.database import SessionFactory
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
        self, *, project_id: UUID, revision_id: UUID
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
                row for row in all_jobs if row.input_payload.get("revision_id") == str(revision_id)
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
            bundle_row = (
                await session.execute(
                    select(ExportBundleArtifactRow).where(
                        ExportBundleArtifactRow.project_id == project_id,
                        ExportBundleArtifactRow.revision_id == revision_id,
                    )
                )
            ).scalar_one_or_none()
            media_runs = {
                row.id: row
                for row in (
                    await session.execute(
                        select(MediaRunRow).where(
                            MediaRunRow.id.in_({item.run_id for item in jobs})
                        )
                    )
                ).scalars()
            } if jobs else {}

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
        lineage_error = _lineage_error(jobs, artifacts, bundle_row, media_runs)
        steps = tuple(
            ExportStepSummary(
                step=step,
                job_id=(jobs[index].id if index < len(jobs) else None),
                status=(jobs[index].status if index < len(jobs) else "pending"),
                artifact_id=(jobs[index].result_artifact_id if index < len(jobs) else None),
                error_code=(jobs[index].error_code if index < len(jobs) else None),
            )
            for index, step in enumerate(EXPORT_STEPS)
        )
        bundle = _public_bundle(bundle_row) if bundle_row is not None else None
        files: tuple[ExportFileSummary, ...] = ()
        manifest_error: str | None = None
        if lineage_error is None:
            try:
                files = self._files(artifacts=artifacts, bundle=bundle_row)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                manifest_error = "EXPORT_MANIFEST_INVALID"
        error_code = lineage_error or manifest_error or next(
            (item.error_code for item in steps if item.error_code), None
        )
        if error_code is not None:
            status = "failed"
        elif (
            bundle is not None
            and bundle.availability is ArtifactAvailability.AVAILABLE
            and len(jobs) == len(EXPORT_STEPS)
            and all(item.status == "succeeded" for item in steps)
        ):
            status = "ready"
        else:
            status = "partial"
        return RevisionExportProjection(
            project_id=revision.project_id,
            revision_id=revision.id,
            source_run_id=revision.source_run_id,
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
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != "export-manifest.v1"
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
            checksum = entry["sha256"]
            byte_size = entry["bytes"]
            artifact_id = entry.get("artifact_id")
            if artifact_id is not None:
                artifact = artifact_by_id.get(artifact_id)
                if artifact is None:
                    raise ValueError("manifest Artifact missing")
                values.append(_audio_file(artifact, filename=filename))
            else:
                values.append(ExportFileSummary(
                    file_id=f"bundle:{bundle.id}:{filename}", filename=filename,
                    category=_bundle_category(filename), media_type=_media_type(filename),
                    byte_size=byte_size, availability=ArtifactAvailability(bundle.availability),
                    checksum=checksum,
                    content_url=f"/api/v1/export-bundles/{bundle.id}/files/{filename}",
                ))
        manifest_size = manifest_path.stat().st_size
        values.append(ExportFileSummary(
            file_id=f"bundle:{bundle.id}:export-manifest.json",
            filename="export-manifest.json", category="manifest", media_type="application/json",
            byte_size=manifest_size, availability=ArtifactAvailability(bundle.availability),
            checksum=bundle.content_hash,
            content_url=f"/api/v1/export-bundles/{bundle.id}/files/export-manifest.json",
        ))
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


def _public_bundle(row: ExportBundleArtifactRow) -> ExportBundleSummary:
    return ExportBundleSummary(
        bundle_id=row.id, project_id=row.project_id, revision_id=row.revision_id,
        availability=ArtifactAvailability(row.availability), content_hash=row.content_hash,
        byte_size=row.byte_size, file_count=row.file_count,
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
        "master" if profile is MediaQualityProfile.CANONICAL_MASTER_V1
        else "delivery" if profile is MediaQualityProfile.DELIVERY_MP3_V1
        else "stem"
    )
    return ExportFileSummary(
        file_id=f"audio:{row.id}", filename=filename, category=category,
        media_type=_media_type(filename), byte_size=row.byte_size,
        availability=ArtifactAvailability(row.availability), checksum=row.content_hash,
        content_url=f"/api/v1/audio-artifacts/{row.id}/content", artifact_id=row.id,
    )


def _bundle_category(filename: str) -> str:
    if filename == "composition.mid":
        return "midi"
    if filename == "project.json":
        return "project"
    return "manifest"


def _media_type(filename: str) -> str:
    return {
        ".json": "application/json", ".mid": "audio/midi",
        ".wav": "audio/wav", ".mp3": "audio/mpeg",
    }.get(Path(filename).suffix.lower(), "application/octet-stream")
