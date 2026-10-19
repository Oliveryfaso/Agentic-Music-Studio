import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from motif_forge.application.rendering import (
    build_candidate_preview_payload,
    build_canonical_render_payload,
    compile_audio_graph,
)
from motif_forge.application.undo import build_inverse_commands
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import (
    EDITOR_COMMAND_ADAPTER,
    RemoveAddedPianoTrackCommand,
    RemoveAddedPianoTrackPayload,
    Selection,
    SetPianoMixCommand,
    SetPianoMixPayload,
    SetTrackParamCommand,
    SetTrackParamPayload,
    apply_commands,
)
from motif_forge.domain.export_plan import plan_export, read_export_plan_json
from motif_forge.domain.ir import (
    ArrangementIRV4,
    PianoMixState,
    PianoTrackMix,
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

DATA = Path(__file__).parents[3] / "src/motif_forge/resources/scores/ode-melody.musicxml"


def ensemble():
    project = UUID(int=528)
    source = score_to_arrangement(
        parse_musicxml(DATA.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    return apply_commands(
        source,
        (
            accompaniment_command(
                source,
                AccompanimentIntent(pattern="broken", chords=("G",) * 16),
                request_id=UUID(int=2),
            ),
        ),
    )


def initial_mix(base):
    return PianoMixState(
        tracks=tuple(
            PianoTrackMix(
                track_id=t.track_id, gain_db=t.gain_db, pan=t.pan, mute=t.mute, solo=t.solo
            )
            for t in base.tracks
        )
    )


def mix_command(base, mix):
    return SetPianoMixCommand(
        command_id=uuid4(),
        client_sequence=0,
        selection=Selection(track_ids=tuple(t.track_id for t in base.tracks)),
        payload=SetPianoMixPayload(mix=mix),
    )


def mixed(base=None, **changes):
    base = base or ensemble()
    state = initial_mix(base)
    if changes:
        state = state.model_copy(
            update={"tracks": (state.tracks[0].model_copy(update=changes), state.tracks[1])}
        )
    command = mix_command(base, state)
    return apply_commands(base, (command,)), command


def test_mix_upgrade_preserves_every_original_track_and_has_exact_l0_inverse():
    base = ensemble()
    before_graph = compile_audio_graph(base).graph
    value, command = mixed(base, gain_db=-6.0, pan=-0.5, solo=True)
    assert isinstance(value, ArrangementIRV4)
    assert value.tracks == base.tracks and value.performance_plan == base.performance_plan
    assert command.actor_kind == "human" and compute_change_impact((command,)) == ChangeImpact.L0
    assert EDITOR_COMMAND_ADAPTER.validate_json(command.model_dump_json()) == command
    assert read_arrangement_json(value.model_dump_json()) == value
    assert versions_for_arrangement(value).compiler == "audio-graph-spec.v4"
    inverse = build_inverse_commands(base, value, (command,), actor_id="human:local")
    assert inverse[0].payload.mix is None
    assert apply_commands(value, inverse) == base
    assert compile_audio_graph(base).graph == before_graph
    assert before_graph["schemaVersion"] == "audio-graph-spec.v3"
    assert "expectedSilence" not in before_graph


def test_mix_change_inverse_restores_full_saved_mix_not_track_defaults():
    base, _ = mixed(gain_db=-8.0, solo=True)
    state = base.piano_mix.model_copy(
        update={
            "tracks": (
                base.piano_mix.tracks[0].model_copy(update={"gain_db": -12.0, "solo": False}),
                base.piano_mix.tracks[1],
            )
        }
    )
    command = mix_command(base, state)
    edited = apply_commands(base, (command,))
    assert (
        apply_commands(
            edited, build_inverse_commands(base, edited, (command,), actor_id="human:local")
        )
        == base
    )
    assert edited.tracks == base.tracks


@pytest.mark.parametrize(
    "changes",
    [{"gain_db": 6.1}, {"gain_db": float("nan")}, {"pan": 1.1}, {"mute": 1}, {"solo": "true"}],
)
def test_mix_schema_rejects_invalid_values(changes):
    with pytest.raises(ValidationError):
        PianoTrackMix(track_id=uuid4(), **changes)


def test_mix_requires_exact_track_coverage_and_human_actor_without_note_payload():
    base = ensemble()
    good = initial_mix(base)
    for tracks in (
        (good.tracks[0],),
        (good.tracks[0], good.tracks[0]),
        (good.tracks[0], good.tracks[1].model_copy(update={"track_id": uuid4()})),
    ):
        with pytest.raises(ValueError, match="PIANO_MIX_TRACKS_INVALID"):
            state = PianoMixState(tracks=tracks)
            apply_commands(base, (mix_command(base, state),))
    command = mix_command(base, good)
    with pytest.raises(ValidationError):
        SetPianoMixCommand.model_validate_json(
            command.model_dump_json().replace('"human"', '"agent"')
        )
    body = command.model_dump(mode="json")
    body["payload"]["notes"] = []
    with pytest.raises(ValidationError):
        EDITOR_COMMAND_ADAPTER.validate_json(json.dumps(body))


def test_mix_refuses_lossy_legacy_initialization_and_single_piano():
    base = ensemble()
    for field, value in (
        ("gain_db", 7.0),
        ("eq", base.tracks[0].eq.model_copy(update={"low_db": 13.0})),
    ):
        invalid = base.model_copy(
            update={"tracks": (base.tracks[0].model_copy(update={field: value}), base.tracks[1])}
        )
        with pytest.raises(ValueError, match="PIANO_MIX_LEGACY_RANGE"):
            apply_commands(invalid, (mix_command(invalid, initial_mix(base)),))
    one = read_arrangement_json(
        apply_commands(
            base,
            (
                RemoveAddedPianoTrackCommand(
                    command_id=uuid4(),
                    client_sequence=0,
                    payload=RemoveAddedPianoTrackPayload(
                        track_id=base.tracks[1].track_id, restore_schema_version="arrangement-ir.v2"
                    ),
                ),
            ),
        ).model_dump_json()
    )
    with pytest.raises(ValueError, match="PIANO_MIX_PROFILE_UNSUPPORTED"):
        apply_commands(one, (mix_command(one, initial_mix(one)),))


def test_mix_rejects_duplicate_truth_and_structural_profile_downgrade():
    base, _ = mixed()
    for parameter, value in (("gain_db", -4.0), ("pan", 0.5), ("mute", True), ("solo", True)):
        with pytest.raises(Exception, match="PIANO_MIX_PARAMETER_CONFLICT"):
            apply_commands(
                base,
                (
                    SetTrackParamCommand(
                        command_id=uuid4(),
                        client_sequence=0,
                        actor_kind="human",
                        payload=SetTrackParamPayload(
                            track_id=base.tracks[1].track_id, parameter=parameter, value=value
                        ),
                    ),
                ),
            )
    with pytest.raises(Exception, match="PIANO_MIX_STRUCTURE_UNSUPPORTED"):
        apply_commands(
            base,
            (
                RemoveAddedPianoTrackCommand(
                    command_id=uuid4(),
                    client_sequence=0,
                    payload=RemoveAddedPianoTrackPayload(
                        track_id=base.tracks[1].track_id, restore_schema_version="arrangement-ir.v3"
                    ),
                ),
            ),
        )


def test_graph_computes_solo_globally_before_stem_selection_and_true_expected_silence():
    value, _ = mixed(pan=-0.75, solo=True)
    graph = compile_audio_graph(value).graph
    by_id = {t["trackId"]: t for t in graph["tracks"]}
    assert graph["schemaVersion"] == "audio-graph-spec.v4" and not graph["expectedSilence"]
    assert by_id[str(value.tracks[0].track_id)]["audible"] is True
    assert by_id[str(value.tracks[0].track_id)]["pan"] == -0.75
    assert by_id[str(value.tracks[1].track_id)]["audible"] is False
    stem = compile_audio_graph(value, render_track_ids=(value.tracks[1].track_id,)).graph
    assert len(stem["tracks"]) == 1 and stem["expectedSilence"] is True
    state = value.piano_mix.model_copy(
        update={
            "tracks": tuple(t.model_copy(update={"mute": True}) for t in value.piano_mix.tracks)
        }
    )
    silent = apply_commands(value, (mix_command(value, state),))
    assert compile_audio_graph(silent).graph["expectedSilence"] is True


def test_versioned_jobs_and_export_plan_retain_ir4_identity():
    value, _ = mixed()
    revision = create_root_state(value.project_id, created_by="human:local").revision.model_copy(
        update={
            "arrangement_ir": value,
            "content_hash": arrangement_content_hash(value),
            "versions": versions_for_arrangement(value),
        }
    )
    job = build_canonical_render_payload(revision, seed=0)
    assert job.schema_version == "canonical-render-job.v4"
    assert job.audio_engine_version == "motif-forge-audio-engine.v4"
    plan = plan_export(revision, seed=0)
    assert (
        plan.schema_version == "export-plan.v5" and plan.engine_version == job.audio_engine_version
    )
    assert read_export_plan_json(plan.model_dump_json()) == plan
    snapshot = CandidateSnapshot(
        candidate_snapshot_id=uuid4(),
        candidate_id=uuid4(),
        base_revision_id=revision.revision_id,
        created_at=datetime.now(UTC),
        project_id=value.project_id,
        candidate_ir=value,
        candidate_content_hash=arrangement_content_hash(value),
        versions=versions_for_arrangement(value),
    )
    preview = build_candidate_preview_payload(snapshot, seed=0)
    assert preview.schema_version == "candidate-preview-job.v4"
    assert preview.audio_graph == job.audio_graph


def test_multiple_mix_commands_in_one_batch_undo_exactly_to_v3_parent():
    base = ensemble()
    first = initial_mix(base)
    first = first.model_copy(
        update={"tracks": (first.tracks[0].model_copy(update={"gain_db": -8.0}), first.tracks[1])}
    )
    second = first.model_copy(
        update={
            "tracks": (
                first.tracks[0].model_copy(update={"pan": -0.5}),
                first.tracks[1].model_copy(update={"solo": True}),
            )
        }
    )
    commands = (
        mix_command(base, first),
        mix_command(base, second),
        mix_command(base, initial_mix(base)),
    )
    commands = tuple(
        command.model_copy(update={"client_sequence": index})
        for index, command in enumerate(commands)
    )
    candidate = apply_commands(base, commands)
    assert candidate.piano_mix == initial_mix(base)
    inverse = build_inverse_commands(base, candidate, commands, actor_id="human:local")
    assert len(inverse) == 3
    assert apply_commands(candidate, inverse) == base


def test_semantic_local_edit_on_v4_preserves_mix_and_original_and_undo():
    from motif_forge.domain.commands import ReplacePianoRangeCommand, ReplacePianoRangePayload
    from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan

    base, _ = mixed(gain_db=-14.0, pan=0.75, mute=True)
    plan = AccompanimentPlan(
        summary="更轻更稀疏",
        bars=tuple(
            BarPlan(bar=i, chord="G", grid=(0,), octave=2, velocity=36) for i in range(9, 13)
        ),
    )
    target = base.tracks[1]
    replacement = compile_piano_plan(
        base, plan, request_id=uuid4(), target_track_id=target.track_id, start_bar=9, end_bar=12
    )
    command = ReplacePianoRangeCommand(
        command_id=uuid4(),
        client_sequence=0,
        actor_kind="agent",
        selection=Selection(track_ids=(target.track_id,), start_tick=8 * 1920, end_tick=12 * 1920),
        payload=ReplacePianoRangePayload(track=replacement, start_bar=9, end_bar=12),
    )
    result = apply_commands(base, (command,))
    assert isinstance(result, ArrangementIRV4) and result.piano_mix == base.piano_mix
    assert result.render_profile == base.render_profile and result.tracks[0] == base.tracks[0]
    assert (
        apply_commands(
            result, build_inverse_commands(base, result, (command,), actor_id="human:local")
        )
        == base
    )
