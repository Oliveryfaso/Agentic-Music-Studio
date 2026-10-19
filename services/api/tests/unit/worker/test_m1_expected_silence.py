from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from motif_forge.application.rendering import build_candidate_preview_payload
from motif_forge.audio.chromium_render import ChromiumRenderError
from motif_forge.audio.transcode import ExportTranscodeError
from motif_forge.config import Settings
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.ir import (
    ArrangementIRV4,
    MixPianoRenderProfile,
    NoteClip,
    NoteEvent,
    PianoMixState,
    PianoTrackMix,
    Section,
    Track,
    TrackType,
)
from motif_forge.domain.media_jobs import ExportMp3JobPayload, MediaQualityProfile, RenderScope
from motif_forge.domain.revisions import (
    CandidateSnapshot,
    create_root_state,
    versions_for_arrangement,
)
from motif_forge.worker import execution


def mixed_revision(silent):
    project = UUID(int=990)
    ids = (UUID(int=991), UUID(int=992))
    arrangement = ArrangementIRV4(
        project_id=project,
        render_profile=MixPianoRenderProfile(),
        sections=(Section(section_id=uuid4(), start_tick=0, end_tick=3840, label="mix test"),),
        tracks=tuple(
            Track(
                track_id=identity,
                track_type=TrackType.INSTRUMENT,
                name="test piano",
                instrument_ref="builtin:jazz-piano",
                clips=(
                    NoteClip(
                        clip_id=uuid4(),
                        start_tick=0,
                        duration_tick=3840,
                        notes=(
                            NoteEvent(note_id=uuid4(), pitch=60, start_tick=0, duration_tick=480),
                        ),
                    ),
                ),
            )
            for identity in ids
        ),
        piano_mix=PianoMixState(
            tracks=tuple(PianoTrackMix(track_id=identity, mute=silent) for identity in ids)
        ),
    )
    return create_root_state(project, created_by="test").revision.model_copy(
        update={
            "arrangement_ir": arrangement,
            "content_hash": arrangement_content_hash(arrangement),
            "versions": versions_for_arrangement(arrangement),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("silent", [False, True])
async def test_export_mp3_allows_zero_only_from_authoritative_ir4(monkeypatch, tmp_path, silent):
    revision = mixed_revision(silent)
    source = SimpleNamespace(
        artifact_id=uuid4(),
        content_hash="a" * 64,
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        revision_id=revision.revision_id,
        render_scope=RenderScope.MASTER,
        arrangement_hash=revision.content_hash,
        encoder_version="motif-forge-audio-engine.v4",
        storage_key="test.wav",
        duration_seconds=4.0,
    )
    payload = ExportMp3JobPayload(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source_artifact_id=source.artifact_id,
        source_content_hash=source.content_hash,
        timeout_seconds=30,
    )
    job = SimpleNamespace(
        project_id=revision.project_id,
        job_id=uuid4(),
        input_payload=payload.model_dump(mode="json"),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(get_revision=AsyncMock(return_value=revision))

    transcode = Mock(return_value="test-result")
    monkeypatch.setattr(execution, "transcode_master_to_mp3", transcode)
    result = await execution._execute_export_transcode(
        job, source, Settings.for_test(artifact_root=tmp_path, temp_root=tmp_path), uow=uow
    )
    assert (
        result == "test-result" and transcode.call_args.kwargs["allow_expected_silence"] is silent
    )
    source.arrangement_hash = "b" * 64
    with pytest.raises(ExportTranscodeError, match="TRANSCODE_JOB_LINEAGE_INVALID"):
        await execution._execute_export_transcode(
            job, source, Settings.for_test(artifact_root=tmp_path, temp_root=tmp_path), uow=uow
        )
    assert transcode.call_count == 1


@pytest.mark.asyncio
async def test_candidate_zero_permission_requires_exact_saved_snapshot_graph(monkeypatch, tmp_path):
    revision = mixed_revision(True)
    snapshot = CandidateSnapshot(
        candidate_snapshot_id=uuid4(),
        candidate_id=uuid4(),
        project_id=revision.project_id,
        base_revision_id=revision.revision_id,
        candidate_ir=revision.arrangement_ir,
        candidate_content_hash=revision.content_hash,
        versions=revision.versions,
        created_at=datetime.now(UTC),
    )
    payload = build_candidate_preview_payload(snapshot, seed=0)
    job = SimpleNamespace(
        project_id=revision.project_id,
        job_id=uuid4(),
        output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        input_payload=payload.model_dump(mode="json"),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(get_candidate_snapshot=AsyncMock(return_value=snapshot))

    render = AsyncMock(
        return_value=SimpleNamespace(storage_key="test-source.wav", duration_seconds=4.0)
    )
    monkeypatch.setattr(execution.ChromiumRenderClient, "render", render)
    transcode = Mock(return_value="test-result")
    monkeypatch.setattr(execution, "transcode_master_to_mp3", transcode)
    await execution._execute_candidate_preview(
        job, uow, Settings.for_test(artifact_root=tmp_path, temp_root=tmp_path)
    )
    assert transcode.call_args.kwargs["allow_expected_silence"] is True
    # A forged self-consistent mute graph still cannot replace a different saved Snapshot.
    audible = revision.arrangement_ir.model_copy(
        update={
            "piano_mix": PianoMixState(
                tracks=tuple(
                    t.model_copy(update={"mute": False})
                    for t in revision.arrangement_ir.piano_mix.tracks
                )
            )
        }
    )
    other = snapshot.model_copy(
        update={
            "candidate_ir": audible,
            "candidate_content_hash": arrangement_content_hash(audible),
        }
    )
    with pytest.raises(ChromiumRenderError, match="CANDIDATE_PREVIEW_LINEAGE_MISMATCH"):
        execution.validate_candidate_preview_lineage(payload, other)
    assert render.call_count == 1
