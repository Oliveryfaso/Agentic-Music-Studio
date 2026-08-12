from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from motif_forge.application.rendering import compile_audio_graph
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.media_jobs import (
    ArtifactLifecycle,
    AudioArtifact,
    BundleAudioInput,
    CanonicalRenderJobPayload,
    ExportBundleJobPayload,
    MediaQualityProfile,
    RenderScope,
)
from pydantic import ValidationError


def test_canonical_audio_artifact_requires_structured_revision_lineage() -> None:
    with pytest.raises(ValueError, match="canonical and delivery outputs require revision lineage"):
        AudioArtifact(
            artifact_id=UUID(int=901),
            project_id=UUID(int=902),
            source_job_id=UUID(int=903),
            content_hash="a" * 64,
            byte_size=1024,
            storage_key="protected/exports/master.wav",
            media_role="canonical_master",
            quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
            container="wav",
            codec="pcm",
            sample_rate_hz=48_000,
            channels=2,
            duration_seconds=72.0,
            bit_depth=24,
            encoder="test",
            encoder_version="v1",
            lifecycle_class=ArtifactLifecycle.PROTECTED,
            created_at=datetime.now(UTC),
        )

PROJECT_ID = UUID("10000000-0000-4000-8000-000000000033")
REVISION_ID = UUID("20000000-0000-4000-8000-000000000033")


def test_master_render_job_pins_revision_graph_engine_seed_and_resource_bounds() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=33).arrangement
    projection = compile_audio_graph(arrangement)

    payload = CanonicalRenderJobPayload(
        project_id=PROJECT_ID,
        revision_id=REVISION_ID,
        render_scope=RenderScope.MASTER,
        render_track_ids=(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        audio_graph=projection.graph,
        audio_graph_hash=projection.graph_hash,
        arrangement_hash=projection.arrangement_hash,
        audio_engine_version="motif-forge-audio-engine.v1",
        seed=33,
        timeout_seconds=180,
        maximum_output_bytes=64 * 1024 * 1024,
    )

    assert payload.schema_version == "canonical-render-job.v1"


def test_stem_render_job_requires_exactly_one_track_and_stem_profile() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=34).arrangement
    track_id = arrangement.tracks[0].track_id
    projection = compile_audio_graph(arrangement, render_track_ids=(track_id,))
    values = {
        "project_id": PROJECT_ID,
        "revision_id": REVISION_ID,
        "render_scope": RenderScope.STEM,
        "render_track_ids": (track_id,),
        "quality_profile": MediaQualityProfile.CANONICAL_STEM_V1,
        "audio_graph": projection.graph,
        "audio_graph_hash": projection.graph_hash,
        "arrangement_hash": projection.arrangement_hash,
        "audio_engine_version": "motif-forge-audio-engine.v1",
        "seed": 34,
        "timeout_seconds": 180,
        "maximum_output_bytes": 64 * 1024 * 1024,
    }

    assert CanonicalRenderJobPayload.model_validate(values, strict=True).render_track_ids == (
        track_id,
    )
    with pytest.raises(ValidationError):
        CanonicalRenderJobPayload.model_validate({**values, "render_track_ids": ()}, strict=True)
    with pytest.raises(ValidationError):
        CanonicalRenderJobPayload.model_validate(
            {**values, "quality_profile": MediaQualityProfile.CANONICAL_MASTER_V1}, strict=True
        )


def test_render_job_rejects_tampered_graph_hash_or_engine_version() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=35).arrangement
    projection = compile_audio_graph(arrangement)
    values = {
        "project_id": PROJECT_ID,
        "revision_id": REVISION_ID,
        "render_scope": RenderScope.MASTER,
        "render_track_ids": (),
        "quality_profile": MediaQualityProfile.CANONICAL_MASTER_V1,
        "audio_graph": projection.graph,
        "audio_graph_hash": "0" * 64,
        "arrangement_hash": projection.arrangement_hash,
        "audio_engine_version": "motif-forge-audio-engine.v1",
        "seed": 35,
        "timeout_seconds": 180,
        "maximum_output_bytes": 64 * 1024 * 1024,
    }

    with pytest.raises(ValidationError, match="audio_graph_hash"):
        CanonicalRenderJobPayload.model_validate(values, strict=True)
    with pytest.raises(ValidationError, match="audio_engine_version"):
        CanonicalRenderJobPayload.model_validate(
            {
                **values,
                "audio_graph_hash": projection.graph_hash,
                "audio_engine_version": "other-engine",
            },
            strict=True,
        )


def test_export_bundle_job_requires_exact_master_mp3_and_four_stems() -> None:
    arrangement = build_s1_composition(PROJECT_ID, seed=36).arrangement
    profiles = (
        MediaQualityProfile.CANONICAL_MASTER_V1,
        MediaQualityProfile.DELIVERY_MP3_V1,
        *(MediaQualityProfile.CANONICAL_STEM_V1 for _ in range(4)),
    )
    inputs = tuple(
        BundleAudioInput(
            artifact_id=UUID(int=500 + index),
            quality_profile=profile,
            content_hash=f"{index:064x}",
            filename=(
                "master.wav"
                if index == 0
                else "master.mp3"
                if index == 1
                else f"stem-{index}.wav"
            ),
        )
        for index, profile in enumerate(profiles, start=1)
    )

    payload = ExportBundleJobPayload(
        project_id=PROJECT_ID,
        revision_id=REVISION_ID,
        seed=36,
        arrangement_hash=__import__(
            "motif_forge.domain.canonical", fromlist=["arrangement_content_hash"]
        ).arrangement_content_hash(arrangement),
        audio_inputs=inputs,
        engine_version="motif-forge-audio-engine.v1",
        trace_refs=("trace:s1",),
    )

    assert payload.schema_version == "export-bundle-job.v1"
    with pytest.raises(ValidationError):
        ExportBundleJobPayload.model_validate(
            {**payload.model_dump(mode="json"), "audio_inputs": list(inputs[:-1])}, strict=True
        )
