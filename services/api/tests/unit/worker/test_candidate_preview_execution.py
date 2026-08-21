from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from motif_forge.application.rendering import build_candidate_preview_payload
from motif_forge.audio.chromium_render import ChromiumRenderError
from motif_forge.audio.transcode import Mp3TranscodeResult
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.revisions import VersionRefs, create_candidate_snapshot, create_root_state
from motif_forge.worker.execution import (
    _cleanup_cancelled_output,
    validate_candidate_preview_lineage,
)


@pytest.mark.asyncio
async def test_worker_rejects_snapshot_lineage_mismatch() -> None:
    project_id = uuid4()
    root = create_root_state(
        project_id,
        created_by="human",
        created_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )
    build = build_s1_composition(project_id, seed=9)
    snapshot = create_candidate_snapshot(
        base_revision=root.revision,
        candidate_ir=build.arrangement,
        candidate_id=uuid4(),
        commands=build.commands,
        source_run_id=uuid4(),
        versions=VersionRefs(compiler="candidate-worker-test.v1"),
        created_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )
    payload = build_candidate_preview_payload(snapshot, seed=0)
    wrong = snapshot.model_copy(update={"candidate_content_hash": "f" * 64})
    with pytest.raises(ChromiumRenderError) as error:
        validate_candidate_preview_lineage(payload, wrong)
    assert error.value.code == "CANDIDATE_PREVIEW_LINEAGE_MISMATCH"


def test_deadline_cleanup_removes_new_candidate_mp3(tmp_path) -> None:
    storage_key = "candidate-preview/test/output.mp3"
    output = tmp_path / storage_key
    output.parent.mkdir(parents=True)
    output.write_bytes(b"generated-after-deadline")
    result = Mp3TranscodeResult(
        storage_key=storage_key,
        sha256="1" * 64,
        byte_size=24,
        duration_seconds=1.0,
        sample_rate_hz=48_000,
        channels=2,
        bitrate_kbps=160,
        created_new=True,
    )

    _cleanup_cancelled_output((object(), result), artifact_root=tmp_path)

    assert not output.exists()
