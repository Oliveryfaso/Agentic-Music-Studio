#!/usr/bin/env python3
"""Run the real canonical Chromium render boundary and verify PCM24 output."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from motif_forge.application.rendering import compile_audio_graph
from motif_forge.audio.chromium_render import ChromiumRenderClient
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.media_jobs import (
    CanonicalRenderJobPayload,
    MediaQualityProfile,
    RenderScope,
)


async def main() -> None:
    root_value = os.environ.get("MOTIF_FORGE_ARTIFACT_ROOT", "").strip()
    service_url = os.environ.get("MOTIF_FORGE_RENDER_SERVICE_URL", "http://localhost:8090")
    if not root_value:
        raise RuntimeError("MOTIF_FORGE_ARTIFACT_ROOT is required")
    root = Path(root_value).resolve()
    temp_root_value = os.environ.get("MOTIF_FORGE_TEMP_ROOT", "").strip()
    if not temp_root_value:
        raise RuntimeError("MOTIF_FORGE_TEMP_ROOT is required")
    temp_root = Path(temp_root_value).resolve()
    project_id = uuid5(NAMESPACE_URL, "motif-forge:s1-real-render-project")
    revision_id = uuid5(NAMESPACE_URL, "motif-forge:s1-real-render-revision")
    job_id = uuid5(NAMESPACE_URL, "motif-forge:s1-real-render-job")
    build = build_s1_composition(project_id, seed=20260812)
    projection = compile_audio_graph(build.arrangement)
    payload = CanonicalRenderJobPayload(
        project_id=project_id,
        revision_id=revision_id,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version="motif-forge-audio-engine.v1",
        seed=20260812,
        timeout_seconds=240,
        maximum_output_bytes=64 * 1024 * 1024,
    )
    result = await ChromiumRenderClient(
        artifact_root=root,
        temp_root=temp_root,
        service_url=service_url,
    ).render(job_id=job_id, payload=payload)
    if result.bit_depth != 24 or result.sample_rate_hz != 48_000 or result.channels != 2:
        raise RuntimeError("S1 canonical media profile mismatch")
    if abs(result.duration_seconds - 72.0) > 1 / 48_000:
        raise RuntimeError("S1 duration mismatch")
    print(
        {
            "storage_key": result.storage_key,
            "sha256": result.sha256,
            "bytes": result.byte_size,
            "duration_seconds": result.duration_seconds,
            "peak": result.peak,
        }
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"S1 render check failed: {exc}", file=sys.stderr)
        raise
