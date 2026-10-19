"""M2 EQ boundaries, exact Undo, and version-bound rendering."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from motif_forge.application.rendering import (
    build_candidate_preview_payload,
    build_canonical_render_payload,
)
from motif_forge.application.undo import build_inverse_commands
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import (
    EDITOR_COMMAND_ADAPTER,
    Selection,
    SetPianoEqCommand,
    SetPianoEqPayload,
    apply_commands,
)
from motif_forge.domain.export_plan import plan_export, read_export_plan_json
from motif_forge.domain.ir import (
    ArrangementIRV5,
    PianoEqProfile,
    PianoEqState,
    PianoTrackEq,
    read_arrangement_json,
)
from motif_forge.domain.policies import compute_change_impact
from motif_forge.domain.revisions import (
    CandidateSnapshot,
    ChangeImpact,
    create_root_state,
    versions_for_arrangement,
)
from pydantic import ValidationError

from .test_m1_mix import ensemble, initial_mix, mix_command, mixed


def eq_state(base, **changes):
    return PianoEqState(
        tracks=tuple(PianoTrackEq(track_id=t.track_id, **changes) for t in base.tracks)
    )


def eq_command(base, eq, sequence=0):
    return SetPianoEqCommand(
        command_id=uuid4(),
        client_sequence=sequence,
        selection=Selection(track_ids=tuple(t.track_id for t in base.tracks)),
        payload=SetPianoEqPayload(eq=eq),
    )


def test_eq_upgrade_snapshot_preserves_source_mix_and_exact_undo():
    from motif_forge.domain.ir import NotePerformance, PerformancePlan

    base, _ = mixed(gain_db=-8.0, pan=-0.5, solo=True)
    track = base.tracks[0]
    clip = track.clips[0]
    base = base.model_copy(
        update={
            "performance_plan": PerformancePlan(
                notes=(
                    NotePerformance(
                        track_id=track.track_id,
                        clip_id=clip.clip_id,
                        note_id=clip.notes[0].note_id,
                        onset_offset_tick=1,
                        velocity_override=79,
                    ),
                )
            )
        }
    )
    action = eq_command(base, eq_state(base, low_gain_db=-6.0, high_gain_db=3.0))
    value = apply_commands(base, (action,))
    assert isinstance(value, ArrangementIRV5)
    assert value.tracks == base.tracks and value.piano_mix == base.piano_mix
    assert value.performance_plan == base.performance_plan
    assert value.render_profile.eq_profile == PianoEqProfile()
    assert compute_change_impact((action,)) == ChangeImpact.L0
    assert EDITOR_COMMAND_ADAPTER.validate_json(action.model_dump_json()) == action
    assert read_arrangement_json(value.model_dump_json()) == value
    assert versions_for_arrangement(value).compiler == "audio-graph-spec.v5"
    inverse = build_inverse_commands(base, value, (action,), actor_id="human:eq")
    assert inverse[0].payload.eq is None
    assert arrangement_content_hash(apply_commands(value, inverse)) == arrangement_content_hash(
        base
    )


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("bypass", "false"),
        ("bypass", 0),
        ("low_gain_db", "-6"),
        ("mid_gain_db", True),
        ("high_gain_db", 12.01),
        ("low_gain_db", float("nan")),
        ("profile_id", "other"),
    ],
)
def test_eq_rejects_unsafe_parameter_values(parameter, value):
    with pytest.raises(ValidationError):
        PianoTrackEq(track_id=uuid4(), **{parameter: value})


def test_eq_rejects_agent_scope_old_profile_and_track_set():
    base, _ = mixed()
    action = eq_command(base, eq_state(base))
    data = json.loads(action.model_dump_json())
    data["actor_kind"] = "agent"
    with pytest.raises(ValidationError):
        EDITOR_COMMAND_ADAPTER.validate_json(json.dumps(data))
    for source, command in (
        (ensemble(), action),
        (
            base,
            action.model_copy(
                update={"selection": Selection(track_ids=(base.tracks[0].track_id,))}
            ),
        ),
        (
            base,
            eq_command(
                base,
                PianoEqState(
                    tracks=(PianoTrackEq(track_id=uuid4()), PianoTrackEq(track_id=uuid4()))
                ),
            ),
        ),
        (base, eq_command(base, None)),
    ):
        with pytest.raises(ValueError):
            apply_commands(source, (command,))
    with pytest.raises(ValidationError):
        PianoEqState(tracks=(PianoTrackEq(track_id=base.tracks[0].track_id),) * 2)


def test_eq_and_mix_batch_inverse_restores_exact_v3_and_v5_mix_keeps_eq():
    base = ensemble()
    changed_mix = initial_mix(base).model_copy(
        update={
            "tracks": (
                initial_mix(base).tracks[0].model_copy(update={"gain_db": -3.0, "pan": 0.5}),
                initial_mix(base).tracks[1].model_copy(update={"solo": True}),
            )
        }
    )
    actions = (
        mix_command(base, initial_mix(base)),
        eq_command(base, eq_state(base, mid_gain_db=4.0), 1),
        mix_command(base, changed_mix),
    )
    actions = tuple(c.model_copy(update={"client_sequence": i}) for i, c in enumerate(actions))
    result = apply_commands(base, actions)
    assert isinstance(result, ArrangementIRV5) and result.piano_eq == actions[1].payload.eq
    assert result.render_profile.engine_version == "motif-forge-audio-engine.v5"
    assert result.piano_mix == changed_mix
    assert (
        apply_commands(result, build_inverse_commands(base, result, actions, actor_id="human:eq"))
        == base
    )
    with pytest.raises(ValueError, match="PIANO_EQ"):
        apply_commands(result, (mix_command(result, None),))
    changed = eq_command(result, eq_state(result, bypass=True, low_gain_db=7.0))
    next_value = apply_commands(result, (changed,))
    assert (
        apply_commands(
            next_value, build_inverse_commands(result, next_value, (changed,), actor_id="human:eq")
        )
        == result
    )


def test_eq_job_export_and_projection_pin_five_and_full_settings():
    base, _ = mixed(mute=True)
    value = apply_commands(base, (eq_command(base, eq_state(base, low_gain_db=-4.0)),))
    revision = create_root_state(value.project_id, created_by="human:eq").revision.model_copy(
        update={
            "arrangement_ir": value,
            "content_hash": arrangement_content_hash(value),
            "versions": versions_for_arrangement(value),
        }
    )
    job = build_canonical_render_payload(revision, seed=0)
    assert job.schema_version == "canonical-render-job.v5"
    assert job.audio_engine_version == "motif-forge-audio-engine.v5"
    graph = job.audio_graph
    assert graph["eqProfile"] == value.render_profile.eq_profile.model_dump(mode="json")
    for track in graph["tracks"]:
        setting = next(eq for eq in value.piano_eq.tracks if str(eq.track_id) == track["trackId"])
        assert track["eq3"] == setting.model_dump(mode="json", exclude={"track_id"})
        assert track["eq"] == {"lowDb": 0.0, "midDb": 0.0, "highDb": 0.0}
    plan = plan_export(revision, seed=0)
    assert plan.schema_version == "export-plan.v6" and plan.render_profile == value.render_profile
    assert read_export_plan_json(plan.model_dump_json()) == plan
    snapshot = CandidateSnapshot(
        candidate_snapshot_id=uuid4(),
        candidate_id=uuid4(),
        base_revision_id=revision.revision_id,
        created_at=datetime.now(UTC),
        project_id=value.project_id,
        candidate_ir=value,
        candidate_content_hash=revision.content_hash,
        versions=revision.versions,
    )
    preview = build_candidate_preview_payload(snapshot, seed=0)
    assert preview.schema_version == "candidate-preview-job.v5" and preview.audio_graph == graph


def eq_revision(silent=False):
    base, _ = mixed(mute=silent)
    if silent:
        base = apply_commands(
            base,
            (
                mix_command(
                    base,
                    base.piano_mix.model_copy(
                        update={
                            "tracks": tuple(
                                t.model_copy(update={"mute": True}) for t in base.piano_mix.tracks
                            )
                        }
                    ),
                ),
            ),
        )
    value = apply_commands(base, (eq_command(base, eq_state(base, low_gain_db=4.0)),))
    return create_root_state(value.project_id, created_by="human:eq").revision.model_copy(
        update={
            "arrangement_ir": value,
            "content_hash": arrangement_content_hash(value),
            "versions": versions_for_arrangement(value),
        }
    )


def eq_snapshot(revision):
    return CandidateSnapshot(
        candidate_snapshot_id=uuid4(),
        candidate_id=uuid4(),
        base_revision_id=revision.revision_id,
        created_at=datetime.now(UTC),
        project_id=revision.project_id,
        candidate_ir=revision.arrangement_ir,
        candidate_content_hash=revision.content_hash,
        versions=revision.versions,
    )


@pytest.mark.parametrize("silent", [False, True])
def test_eq_worker_dispatch_recipe_and_authoritative_lineage(silent):
    import hashlib
    from types import SimpleNamespace

    from motif_forge.audio.chromium_render import ChromiumRenderError
    from motif_forge.worker import execution

    revision = eq_revision(silent)
    snapshot = eq_snapshot(revision)
    payload = build_candidate_preview_payload(snapshot, seed=0)
    assert (
        execution._parse_candidate_preview_payload(
            SimpleNamespace(input_payload=payload.model_dump(mode="json"))
        )
        == payload
    )
    canonical = build_canonical_render_payload(revision, seed=0)
    assert (
        execution._parse_canonical_render_payload(
            SimpleNamespace(input_payload=canonical.model_dump(mode="json"))
        )
        == canonical
    )
    recipe = execution._candidate_preview_rebuild_recipe(payload)
    assert recipe.policy_version == "candidate-preview-render.v5"
    assert recipe.validation_rules[-1] == ("expected-silence.v1" if silent else "non-silence.v1")
    graph = json.loads(json.dumps(payload.audio_graph))
    graph["tracks"][0]["eq3"]["low_gain_db"] = -8.0
    forged = payload.model_copy(
        update={
            "audio_graph": graph,
            "audio_graph_hash": hashlib.sha256(
                json.dumps(
                    graph,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
        }
    )
    with pytest.raises(ChromiumRenderError, match="CANDIDATE_PREVIEW_LINEAGE_MISMATCH"):
        execution.validate_candidate_preview_lineage(forged, snapshot)


def test_eq_local_semantic_edit_preserves_mix_eq_and_exact_inverse():
    from motif_forge.domain.commands import ReplacePianoRangeCommand, ReplacePianoRangePayload
    from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan

    base = eq_revision().arrangement_ir
    target = base.tracks[1]
    plan = AccompanimentPlan(
        summary="更轻更稀疏",
        bars=tuple(
            BarPlan(bar=i, chord="G", grid=(0,), octave=2, velocity=36) for i in range(9, 13)
        ),
    )
    track = compile_piano_plan(
        base, plan, request_id=uuid4(), target_track_id=target.track_id, start_bar=9, end_bar=12
    )
    command = ReplacePianoRangeCommand(
        command_id=uuid4(),
        client_sequence=0,
        actor_kind="agent",
        selection=Selection(track_ids=(target.track_id,), start_tick=8 * 1920, end_tick=12 * 1920),
        payload=ReplacePianoRangePayload(track=track, start_bar=9, end_bar=12),
    )
    result = apply_commands(base, (command,))
    assert isinstance(result, ArrangementIRV5)
    assert (result.piano_eq, result.piano_mix, result.render_profile, result.tracks[0]) == (
        base.piano_eq,
        base.piano_mix,
        base.render_profile,
        base.tracks[0],
    )
    assert (
        apply_commands(
            result, build_inverse_commands(base, result, (command,), actor_id="human:eq")
        )
        == base
    )


@pytest.mark.parametrize(
    "mutation", ["missing_profile", "missing_setting", "boolean_profile", "gain_string"]
)
def test_eq_job_rejects_incomplete_or_coerced_graph_configuration(mutation):
    import hashlib

    from motif_forge.domain.media_jobs import CanonicalRenderJobPayloadV5

    payload = build_canonical_render_payload(eq_revision(), seed=0)
    data = json.loads(payload.model_dump_json())
    graph = data["audio_graph"]
    if mutation == "missing_profile":
        graph["eqProfile"] = {}
    elif mutation == "missing_setting":
        graph["tracks"][0]["eq3"].pop("bypass")
    elif mutation == "boolean_profile":
        graph["eqProfile"]["shelf_slope"] = True
    else:
        graph["tracks"][0]["eq3"]["low_gain_db"] = "4"
    data["audio_graph_hash"] = hashlib.sha256(
        json.dumps(
            graph, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()
    with pytest.raises(ValidationError):
        CanonicalRenderJobPayloadV5.model_validate_json(json.dumps(data))


@pytest.mark.asyncio
@pytest.mark.parametrize("silent", [False, True])
async def test_eq_candidate_and_mp3_permission_comes_from_exact_authoritative_graph(
    monkeypatch, tmp_path, silent
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from motif_forge.config import Settings
    from motif_forge.domain.media_jobs import ExportMp3JobPayload, MediaQualityProfile, RenderScope
    from motif_forge.worker import execution

    revision = eq_revision(silent)
    snapshot = eq_snapshot(revision)
    payload = build_candidate_preview_payload(snapshot, seed=0)
    job = SimpleNamespace(
        project_id=revision.project_id,
        job_id=uuid4(),
        output_quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        input_payload=payload.model_dump(mode="json"),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            get_candidate_snapshot=AsyncMock(return_value=snapshot),
            get_revision=AsyncMock(return_value=revision),
        )

    settings = Settings.for_test(artifact_root=tmp_path, temp_root=tmp_path)
    render = AsyncMock(return_value=SimpleNamespace(storage_key="test.wav", duration_seconds=4.0))
    transcode = Mock(return_value="test-result")
    monkeypatch.setattr(execution.ChromiumRenderClient, "render", render)
    monkeypatch.setattr(execution, "transcode_master_to_mp3", transcode)
    await execution._execute_candidate_preview(job, uow, settings)
    assert transcode.call_args.kwargs["allow_expected_silence"] is silent
    source = SimpleNamespace(
        artifact_id=uuid4(),
        content_hash="a" * 64,
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        revision_id=revision.revision_id,
        render_scope=RenderScope.MASTER,
        arrangement_hash=revision.content_hash,
        encoder_version="motif-forge-audio-engine.v5",
        storage_key="test.wav",
        duration_seconds=4.0,
    )
    mp3 = ExportMp3JobPayload(
        project_id=revision.project_id,
        revision_id=revision.revision_id,
        source_artifact_id=source.artifact_id,
        source_content_hash=source.content_hash,
        timeout_seconds=30,
    )
    job.input_payload = mp3.model_dump(mode="json")
    await execution._execute_export_transcode(job, source, settings, uow=uow)
    assert transcode.call_args.kwargs["allow_expected_silence"] is silent


def test_eq_rebuild_bundle_and_public_reader_keep_complete_pin(tmp_path):
    import hashlib
    from types import SimpleNamespace

    from motif_forge.application.exporting import write_export_bundle
    from motif_forge.application.media_jobs import _compile_rehydrate_payload
    from motif_forge.domain.exporting import AudioExportRef, ExportBundleRequestV2
    from motif_forge.domain.media_jobs import (
        ArtifactAvailability,
        ArtifactLifecycle,
        AudioArtifact,
        EqExportBundleArtifactV6,
        MediaQualityProfile,
        RenderScope,
        WorkerEvent,
    )
    from motif_forge.infrastructure.persistence.export_reads import _public_bundle
    from motif_forge.infrastructure.persistence.media_jobs import (
        _export_bundle_from_row,
        _export_bundle_values,
    )
    from motif_forge.worker import execution

    revision = eq_revision()
    snapshot = eq_snapshot(revision)
    payload = build_candidate_preview_payload(snapshot, seed=0)
    recipe = execution._candidate_preview_rebuild_recipe(payload)
    preview = AudioArtifact(
        artifact_id=uuid4(),
        project_id=revision.project_id,
        candidate_snapshot_id=snapshot.candidate_snapshot_id,
        arrangement_hash=revision.content_hash,
        render_scope=RenderScope.MASTER,
        source_job_id=uuid4(),
        content_hash="a" * 64,
        byte_size=100,
        storage_key="candidate/preview.mp3",
        media_role="candidate_preview",
        quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        container="mp3",
        codec="mp3",
        sample_rate_hz=48000,
        channels=2,
        bitrate_kbps=160,
        duration_seconds=4.0,
        encoder="test",
        encoder_version=payload.audio_engine_version,
        lifecycle_class=ArtifactLifecycle.REBUILDABLE,
        availability=ArtifactAvailability.EVICTED,
        rebuild_recipe=recipe,
        recipe_hash=recipe.content_hash,
        created_at=datetime.now(UTC),
        evicted_at=datetime.now(UTC),
    )
    rebuilt = _compile_rehydrate_payload(preview, project_id=revision.project_id)
    assert rebuilt.schema_version == "candidate-preview-job.v5"
    assert (
        rebuilt.audio_graph == payload.audio_graph
        and rebuilt.expected_recipe_hash == recipe.content_hash
    )
    assert execution._candidate_preview_rebuild_recipe(rebuilt).content_hash == recipe.content_hash
    plan = plan_export(revision, seed=0, include_mp3=False)
    audio = b"self-authored-pinned-export-fixture"
    (tmp_path / "master.wav").write_bytes(audio)
    ref = AudioExportRef(
        artifact_id=uuid4(),
        quality_profile=MediaQualityProfile.CANONICAL_MASTER_V1,
        storage_key="master.wav",
        sha256=hashlib.sha256(audio).hexdigest(),
        byte_size=len(audio),
        filename="master.wav",
    )
    request = ExportBundleRequestV2(
        plan=plan,
        plan_hash=plan.content_hash,
        arrangement=revision.arrangement_ir,
        audio_exports=(ref,),
        trace_refs=("test:m2",),
    )
    result = write_export_bundle(artifact_root=tmp_path, request=request)
    provenance = json.loads((tmp_path / result.storage_prefix / "provenance.json").read_text())
    assert provenance["piano_eq"] == revision.arrangement_ir.piano_eq.model_dump(mode="json")
    assert provenance["eq_profile"] == revision.arrangement_ir.render_profile.eq_profile.model_dump(
        mode="json"
    )
    receipt = EqExportBundleArtifactV6(
        artifact_id=uuid4(),
        project_id=revision.project_id,
        source_job_id=uuid4(),
        revision_id=revision.revision_id,
        content_hash=result.manifest_sha256,
        byte_size=result.total_bytes,
        storage_prefix=result.storage_prefix,
        file_count=result.file_count,
        arrangement_hash=revision.content_hash,
        engine_version=plan.engine_version,
        seed=0,
        input_artifact_ids=(ref.artifact_id,),
        plan=plan,
        plan_hash=plan.content_hash,
        created_at=datetime.now(UTC),
    )
    row = SimpleNamespace(**_export_bundle_values(receipt))
    assert _export_bundle_from_row(row) == receipt
    assert _public_bundle(row).export_plan == plan
    event = WorkerEvent(
        event_id="test:m2:completed",
        job_id=receipt.source_job_id,
        event_type="job.completed",
        artifact=receipt,
        occurred_at=datetime.now(UTC),
    )
    assert event.artifact.schema_version == "export-bundle-artifact.v6"
    assert write_export_bundle(artifact_root=tmp_path, request=request).created_new is False


def test_eq_rejects_legacy_parameter_and_profile_shortcuts():
    from motif_forge.domain.commands import (
        SetPianoProfileCommand,
        SetPianoProfilePayload,
        SetTrackParamCommand,
        SetTrackParamPayload,
    )

    base = eq_revision().arrangement_ir
    target = base.tracks[1]
    legacy = SetTrackParamCommand(
        command_id=uuid4(),
        client_sequence=0,
        actor_kind="human",
        selection=Selection(track_ids=(target.track_id,)),
        payload=SetTrackParamPayload(track_id=target.track_id, parameter="eq_low_db", value=6.0),
    )
    with pytest.raises(ValueError, match="PIANO_EQ_PARAMETER_CONFLICT"):
        apply_commands(base, (legacy,))
    profile = SetPianoProfileCommand(
        command_id=uuid4(),
        client_sequence=0,
        selection=Selection(track_ids=tuple(t.track_id for t in base.tracks)),
        payload=SetPianoProfilePayload(render_profile=None),
    )
    with pytest.raises(ValueError, match="PIANO_MIX_STRUCTURE_UNSUPPORTED"):
        apply_commands(base, (profile,))
