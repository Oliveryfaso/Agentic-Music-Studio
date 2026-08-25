from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.export_reads import (
    ExportBundleSummary,
    ExportFileSummary,
    ExportStepSummary,
    ReadRevisionExport,
    ResolveBundleFile,
    RevisionExportProjection,
    StoredExportBundle,
)
from motif_forge.application.generation import EXPORT_STEPS
from motif_forge.domain.media_jobs import ArtifactAvailability


def uid(value: int) -> UUID:
    return UUID(int=value)


class FakeExportStore:
    projection: RevisionExportProjection | None = None
    bundle: StoredExportBundle | None = None

    async def read_revision_export(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionExportProjection | None:
        if self.projection and (
            self.projection.project_id,
            self.projection.revision_id,
        ) == (project_id, revision_id):
            return self.projection
        return None

    async def read_bundle(self, bundle_id: UUID) -> StoredExportBundle | None:
        return self.bundle if self.bundle and self.bundle.bundle_id == bundle_id else None


def ready_projection() -> RevisionExportProjection:
    return RevisionExportProjection(
        project_id=uid(1), revision_id=uid(2), source_run_id=uid(3), status="ready",
        bundle=ExportBundleSummary(
            bundle_id=uid(20), project_id=uid(1), revision_id=uid(2),
            availability=ArtifactAvailability.AVAILABLE,
            content_hash="a" * 64, byte_size=100, file_count=13,
        ),
        steps=tuple(
            ExportStepSummary(step=step, job_id=uid(100 + index), status="succeeded",
                              artifact_id=uid(200 + index), error_code=None)
            for index, step in enumerate(EXPORT_STEPS)
        ),
        files=(ExportFileSummary(
            file_id="audio:00000000-0000-0000-0000-0000000000c8",
            filename="master.wav", category="master", media_type="audio/wav",
            byte_size=12, availability=ArtifactAvailability.AVAILABLE,
            checksum="b" * 64,
            content_url="/api/v1/audio-artifacts/00000000-0000-0000-0000-0000000000c8/content",
            artifact_id=uid(200),
        ),),
    )


@pytest.mark.asyncio
async def test_export_projection_preserves_exact_step_order_and_public_data() -> None:
    store = FakeExportStore()
    store.projection = ready_projection()

    projection = await ReadRevisionExport(store)(project_id=uid(1), revision_id=uid(2))

    assert tuple(step.step for step in projection.steps) == EXPORT_STEPS
    assert projection.status == "ready"
    serialized = projection.model_dump_json()
    assert "storage_key" not in serialized
    assert "/Volumes/" not in serialized


@pytest.mark.asyncio
async def test_missing_or_cross_project_revision_is_not_found() -> None:
    store = FakeExportStore()
    store.projection = ready_projection()

    with pytest.raises(ApplicationError) as captured:
        await ReadRevisionExport(store)(project_id=uid(99), revision_id=uid(2))

    assert captured.value.code == "REVISION_NOT_FOUND"


@pytest.mark.asyncio
async def test_bundle_file_requires_safe_manifest_member_and_protocol_checksum(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "safe" / "bundle"
    bundle_dir.mkdir(parents=True)
    content = b'{"schema_version":"project.v1"}'
    checksum = hashlib.sha256(content).hexdigest()
    (bundle_dir / "project.json").write_bytes(content)
    (bundle_dir / "export-manifest.json").write_text(json.dumps({
        "schema_version": "export-manifest.v1",
        "project_id": str(uid(1)), "revision_id": str(uid(2)),
        "files": [{"filename": "project.json", "sha256": checksum, "bytes": len(content)}],
    }))
    store = FakeExportStore()
    store.bundle = StoredExportBundle(
        **ready_projection().bundle.model_dump(mode="python"), storage_prefix="safe/bundle"
    )

    result = await ResolveBundleFile(store, artifact_root=tmp_path)(uid(20), "project.json")

    assert result.path == bundle_dir / "project.json"
    assert result.media_type == "application/json"
    for unsafe in ("../project.json", "safe/project.json", ".", ""):
        with pytest.raises(ApplicationError) as captured:
            await ResolveBundleFile(store, artifact_root=tmp_path)(uid(20), unsafe)
        assert captured.value.code == "EXPORT_FILE_NAME_INVALID"


@pytest.mark.asyncio
async def test_bundle_file_rejects_checksum_mismatch(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "safe" / "bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "project.json").write_text("changed")
    (bundle_dir / "export-manifest.json").write_text(json.dumps({
        "schema_version": "export-manifest.v1",
        "project_id": str(uid(1)), "revision_id": str(uid(2)),
        "files": [{"filename": "project.json", "sha256": "b" * 64, "bytes": 7}],
    }))
    store = FakeExportStore()
    store.bundle = StoredExportBundle(
        **ready_projection().bundle.model_dump(mode="python"), storage_prefix="safe/bundle"
    )

    with pytest.raises(ApplicationError) as captured:
        await ResolveBundleFile(store, artifact_root=tmp_path)(uid(20), "project.json")

    assert captured.value.code == "EXPORT_FILE_INTEGRITY_INVALID"
