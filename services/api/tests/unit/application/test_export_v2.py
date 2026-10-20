from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest
from motif_forge.application import generation
from motif_forge.application.exporting import write_export_bundle
from motif_forge.domain import exporting as contract
from motif_forge.domain import media_jobs
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.revisions import create_root_state
from pydantic import ValidationError


def single_track_revision():
    base = create_root_state(UUID(int=2101), created_by="test").revision
    arrangement = build_s1_composition(base.project_id, seed=7).arrangement
    arrangement = arrangement.model_copy(update={"tracks": (arrangement.tracks[0],)})
    return base.model_copy(
        update={
            "arrangement_ir": arrangement,
            "content_hash": arrangement_content_hash(arrangement),
        }
    )


def audio_refs(plan, tmp_path):
    refs = []
    for i, (filename, profile) in enumerate(plan.audio_files):
        blob = f"self-authored-file-fixture-{i}".encode()
        key = f"protected/test-export/{filename}"
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        refs.append(
            contract.AudioExportRef(
                artifact_id=UUID(int=2200 + i),
                quality_profile=profile,
                storage_key=key,
                sha256=hashlib.sha256(blob).hexdigest(),
                byte_size=len(blob),
                filename=filename,
            )
        )
    return tuple(refs)


@pytest.mark.parametrize(
    "include_mp3,stem_count,want", [(False, 0, 8), (True, 0, 9), (True, 1, 10)]
)
def test_single_track_bundle_has_exact_requested_files_without_invented_stems(
    tmp_path, include_mp3, stem_count, want
):
    revision = single_track_revision()
    stems = (revision.arrangement_ir.tracks[0].track_id,) if stem_count else ()
    plan = contract.plan_export(revision, seed=7, include_mp3=include_mp3, stem_track_ids=stems)
    refs = audio_refs(plan, tmp_path)
    request = contract.ExportBundleRequestV2(
        plan=plan,
        plan_hash=plan.content_hash,
        arrangement=revision.arrangement_ir,
        audio_exports=refs,
        trace_refs=("test:a2",),
    )
    result = write_export_bundle(artifact_root=tmp_path, request=request)
    manifest = json.loads((tmp_path / result.storage_prefix / "export-manifest.json").read_text())
    assert result.file_count == want
    assert manifest["schema_version"] == "export-manifest.v2"
    assert manifest["export_plan_hash"] == plan.content_hash
    assert {r["filename"] for r in manifest["files"]} == {n for n, _ in plan.audio_files} | {
        "project.json",
        "composition.mid",
        "credits.json",
        "license.json",
        "provenance.json",
        "trace.json",
    }
    assert write_export_bundle(artifact_root=tmp_path, request=request).created_new is False


def test_plan_is_bound_to_revision_and_actual_tracks():
    revision = single_track_revision()
    with pytest.raises(ValueError, match="EXPORT_TRACK_NOT_IN_REVISION"):
        contract.plan_export(revision, seed=7, stem_track_ids=(UUID(int=9999),))
    plan = contract.plan_export(revision, seed=7)
    altered = revision.model_copy(update={"revision_id": UUID(int=9998)})
    with pytest.raises(ValueError, match="EXPORT_PLAN_REVISION_MISMATCH"):
        contract.verify_export_plan_revision(plan, altered)


def test_v2_cursor_counts_dynamic_audio_steps_and_rejects_rewritten_plan():
    revision = single_track_revision()
    plan = contract.plan_export(revision, seed=7)
    cursor = contract.CompleteExportCursorV2(
        plan=plan,
        plan_hash=plan.content_hash,
        thread_id="test:a2",
        completed_steps=("master",),
        completed_job_ids=(UUID(int=2301),),
        audio_artifact_ids=(UUID(int=2302),),
        media_run_id=UUID(int=2303),
    )
    assert cursor.pending_steps == ("mp3", "bundle")
    with pytest.raises(ValidationError, match="EXPORT_PLAN_HASH_MISMATCH"):
        contract.CompleteExportCursorV2(plan=plan, plan_hash="f" * 64, thread_id="test:a2")
    with pytest.raises(ValidationError, match="ordered export prefix"):
        contract.CompleteExportCursorV2(
            plan=plan,
            plan_hash=plan.content_hash,
            thread_id="test:a2",
            completed_steps=("mp3",),
            completed_job_ids=(UUID(int=2301),),
            audio_artifact_ids=(UUID(int=2302),),
            media_run_id=UUID(int=2303),
        )


def test_legacy_cursor_roundtrip_and_unsupported_version_remain_explicit():
    revision = single_track_revision()
    old = generation.CompleteExportCursor(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        thread_id="test:legacy",
        seed=7,
    )
    raw = old.model_dump_json()
    assert generation.read_complete_export_cursor(raw).model_dump_json() == raw
    plan = contract.plan_export(revision, seed=7)
    new = contract.CompleteExportCursorV2(
        plan=plan, plan_hash=plan.content_hash, thread_id="test:a2"
    )
    assert generation.read_complete_export_cursor(new.model_dump_json()) == new
    with pytest.raises(ValueError, match="EXPORT_CURSOR_VERSION_UNSUPPORTED"):
        generation.read_complete_export_cursor('{"schema_version":"complete-export-cursor.v9"}')
    assert old.pending_steps == generation.EXPORT_STEPS


def test_v2_job_requires_the_exact_plan_inputs_while_v1_stays_six_inputs(tmp_path):
    revision = single_track_revision()
    plan = contract.plan_export(revision, seed=7)
    inputs = tuple(
        media_jobs.BundleAudioInput(
            artifact_id=r.artifact_id,
            quality_profile=r.quality_profile,
            content_hash=r.sha256,
            filename=r.filename,
        )
        for r in audio_refs(plan, tmp_path)
    )
    job = media_jobs.ExportBundleJobPayloadV2(
        plan=plan, plan_hash=plan.content_hash, audio_inputs=inputs, trace_refs=("test:a2",)
    )
    assert len(job.audio_inputs) == 2
    with pytest.raises(ValidationError):
        media_jobs.ExportBundleJobPayloadV2(
            plan=plan, plan_hash=plan.content_hash, audio_inputs=inputs[:1], trace_refs=("test:a2",)
        )
    with pytest.raises(ValidationError):
        media_jobs.ExportBundleJobPayload(
            project_id=revision.project_id,
            revision_id=revision.revision_id,
            seed=7,
            arrangement_hash=revision.content_hash,
            audio_inputs=inputs,
            engine_version="motif-forge-audio-engine.v1",
            trace_refs=("test:legacy",),
        )


def test_reordered_v2_inputs_reuse_the_same_content_addressed_bundle(tmp_path):
    revision = single_track_revision()
    plan = contract.plan_export(revision, seed=7)
    refs = audio_refs(plan, tmp_path)
    request = contract.ExportBundleRequestV2(
        plan=plan,
        plan_hash=plan.content_hash,
        arrangement=revision.arrangement_ir,
        audio_exports=refs,
        trace_refs=("test:a2",),
    )
    first = write_export_bundle(artifact_root=tmp_path, request=request)
    reordered = contract.ExportBundleRequestV2(
        plan=plan,
        plan_hash=plan.content_hash,
        arrangement=revision.arrangement_ir,
        audio_exports=tuple(reversed(refs)),
        trace_refs=("test:a2",),
    )
    second = write_export_bundle(artifact_root=tmp_path, request=reordered)
    assert second.storage_prefix == first.storage_prefix
    assert second.created_new is False


def test_v2_preparation_does_not_publish_builtin_credits_for_unapproved_sample_packs():
    revision = single_track_revision()
    track = revision.arrangement_ir.tracks[0].model_copy(
        update={"instrument_ref": "external:unapproved-piano"}
    )
    arrangement = revision.arrangement_ir.model_copy(update={"tracks": (track,)})
    revision = revision.model_copy(
        update={
            "arrangement_ir": arrangement,
            "content_hash": arrangement_content_hash(arrangement),
        }
    )
    with pytest.raises(ValueError, match="EXPORT_SOURCE_PROFILE_UNSUPPORTED"):
        contract.plan_export(revision, seed=7)


def test_v2_bundle_receipt_accepts_actual_plan_and_rejects_forged_identity():
    from datetime import UTC, datetime

    revision = single_track_revision()
    plan = contract.plan_export(revision, seed=7, include_mp3=False)
    artifact_type = getattr(media_jobs, "ExportBundleArtifactV2", None)
    assert artifact_type is not None, "production needs a versioned dynamic Bundle receipt"
    receipt = artifact_type(
        artifact_id=UUID(int=5200),
        project_id=revision.project_id,
        source_job_id=UUID(int=5201),
        revision_id=revision.revision_id,
        content_hash="a" * 64,
        byte_size=1024,
        storage_prefix="protected/exports/one",
        file_count=8,
        arrangement_hash=revision.content_hash,
        engine_version="motif-forge-audio-engine.v1",
        seed=7,
        input_artifact_ids=(UUID(int=5202),),
        plan=plan,
        plan_hash=plan.content_hash,
        created_at=datetime.now(UTC),
    )
    event = media_jobs.WorkerEvent(
        event_id="job:v2-completed",
        job_id=receipt.source_job_id,
        event_type="job.completed",
        artifact=receipt,
        occurred_at=datetime.now(UTC),
    )
    assert event.artifact.schema_version == "export-bundle-artifact.v2"
    assert event.artifact.file_count == 8
    with pytest.raises(ValidationError, match="EXPORT_PLAN_HASH_MISMATCH"):
        artifact_type.model_validate({**receipt.model_dump(), "plan_hash": "0" * 64})
    with pytest.raises(ValidationError, match="EXPORT_PLAN_ARTIFACT_MISMATCH"):
        artifact_type.model_validate({**receipt.model_dump(), "revision_id": UUID(int=999)})


def test_export_v2_run_cannot_hide_behind_legacy_schema_without_plan():
    from datetime import UTC, datetime

    with pytest.raises(ValidationError, match="EXPORT_RUN_PLAN_INVALID"):
        media_jobs.MediaRun(
            run_id=UUID(int=6000),
            project_id=UUID(int=6001),
            thread_id="unsupported-run",
            run_type="complete_song_export.v2",
            waiting_for_job_id=UUID(int=6002),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


def test_explicit_export_request_ids_separate_retry_jobs_without_changing_revision():
    revision = single_track_revision()
    first = contract.plan_export(revision, seed=7, request_id=UUID(int=7101))
    repeated = contract.plan_export(revision, seed=7, request_id=UUID(int=7101))
    retried = contract.plan_export(revision, seed=7, request_id=UUID(int=7102))
    assert first.content_hash == repeated.content_hash
    assert first.content_hash != retried.content_hash
    assert first.arrangement_hash == retried.arrangement_hash == revision.content_hash
    old = contract.plan_export(revision, seed=7)
    assert "request_id" not in old.model_dump(mode="json")


@pytest.mark.parametrize(
    "score_id",
    [
        "mutopia-528-melody.v1",
        "c01-minuet-g-a16.v1",
        "c02-la-candeur-a8.v1",
        "j01-bethena-a-first8.v1",
    ],
)
def test_classical_two_part_export_binds_new_job_plan_and_score_rights(tmp_path, score_id):
    from uuid import uuid4

    from motif_forge.application.classical_import import reviewed_score
    from motif_forge.application.rendering import build_canonical_render_payload
    from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
    from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
    from motif_forge.domain.commands import apply_commands
    from motif_forge.domain.revisions import versions_for_arrangement

    project = uuid4()
    source, xml = reviewed_score(score_id)
    original = score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref="score:" + score_id
    )
    candidate = apply_commands(
        original,
        (
            accompaniment_command(
                original,
                AccompanimentIntent(
                    pattern="roots", chords=tuple(source["default_chords"]), octave=2, velocity=54
                ),
                request_id=uuid4(),
            ),
        ),
    )
    revision = create_root_state(project, created_by="test").revision.model_copy(
        update={
            "arrangement_ir": candidate,
            "content_hash": arrangement_content_hash(candidate),
            "versions": versions_for_arrangement(candidate),
        }
    )
    job = build_canonical_render_payload(revision, seed=0)
    assert job.schema_version == "canonical-render-job.v3" and len(job.audio_graph["tracks"]) == 2
    plan = contract.plan_export(revision, seed=0, include_mp3=False)
    assert plan.schema_version == "export-plan.v4" and len(plan.track_ids) == 2
    request = contract.ExportBundleRequestV2(
        plan=plan,
        plan_hash=plan.content_hash,
        arrangement=candidate,
        audio_exports=audio_refs(plan, tmp_path),
        trace_refs=("test:classical-source",),
    )
    result = write_export_bundle(artifact_root=tmp_path, request=request)
    credits = json.loads((tmp_path / result.storage_prefix / "credits.json").read_text())
    score_credit = next(c for c in credits["credits"] if c.get("score_id") == source["score_id"])
    assert (
        score_credit["source_sha256"] == source["sha256"]
        and score_credit["musicxml_sha256"] == source["musicxml_sha256"]
    )
    license = json.loads((tmp_path / result.storage_prefix / "license.json").read_text())
    if "sources" in source:
        assert score_credit["sources"] == source["sources"]
        assert score_credit["conversion_losses"] == source["conversion_losses"]
        assert score_credit["sha256_scope"] == source["sha256_scope"]
    assert any(
        item.get("license") == "Public Domain" and item.get("score_id") == source["score_id"]
        for item in license["assets"]
    )


def test_ensemble_bundle_public_read_keeps_versioned_plan():
    from types import SimpleNamespace

    from motif_forge.domain.export_plan import EnsembleExportPlanV4
    from motif_forge.domain.ir import EnsemblePianoRenderProfile
    from motif_forge.infrastructure.persistence.export_reads import _public_bundle

    plan = EnsembleExportPlanV4(
        project_id=UUID(int=1),
        revision_id=UUID(int=2),
        arrangement_hash="a" * 64,
        seed=0,
        track_ids=(UUID(int=3),),
        render_profile=EnsemblePianoRenderProfile(),
    )
    row = SimpleNamespace(
        id=UUID(int=4),
        project_id=plan.project_id,
        revision_id=plan.revision_id,
        availability="available",
        content_hash="b" * 64,
        byte_size=100,
        file_count=8,
        schema_version="export-bundle-artifact.v4",
        export_plan=plan.model_dump(mode="json"),
        plan_hash=plan.content_hash,
    )
    assert _public_bundle(row).export_plan == plan
