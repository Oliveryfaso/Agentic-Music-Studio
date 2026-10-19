from __future__ import annotations

from uuid import UUID

import pytest
from motif_forge.domain.canonical import arrangement_content_hash, canonical_json_bytes
from motif_forge.domain.ir import (
    ArrangementIR,
    ArrangementIRV2,
    NoteClip,
    NoteEvent,
    NotePerformance,
    PerformancePlan,
    PianoRenderProfile,
    Section,
    Track,
    TrackType,
    read_arrangement_json,
)


def uid(n: int) -> UUID:
    return UUID(int=n)


def score() -> ArrangementIR:
    return ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(2), start_tick=0, end_tick=1920, label="self authored"),),
        tracks=(
            Track(
                track_id=uid(3),
                track_type=TrackType.INSTRUMENT,
                name="piano",
                instrument_ref="builtin:jazz-piano",
                clips=(
                    NoteClip(
                        clip_id=uid(4),
                        start_tick=0,
                        duration_tick=1920,
                        notes=(
                            NoteEvent(note_id=uid(5), pitch=60, start_tick=0, duration_tick=240),
                            NoteEvent(note_id=uid(6), pitch=64, start_tick=480, duration_tick=240),
                        ),
                    ),
                ),
            ),
        ),
    )


def piano(*, events=()) -> ArrangementIRV2:
    return ArrangementIRV2.model_validate(
        {
            **score().model_dump(),
            "schema_version": "arrangement-ir.v2",
            "render_profile": PianoRenderProfile(),
            "performance_plan": PerformancePlan(notes=tuple(events)),
        }
    )


def event(note=5, **kwargs) -> NotePerformance:
    return NotePerformance(track_id=uid(3), clip_id=uid(4), note_id=uid(note), **kwargs)


def test_v1_reader_keeps_original_bytes_and_v2_roundtrip_binds_performance() -> None:
    original = score()
    assert canonical_json_bytes(
        read_arrangement_json(original.model_dump_json())
    ) == canonical_json_bytes(original)
    value = piano(events=(event(velocity_override=72, onset_offset_tick=8),))
    reloaded = read_arrangement_json(value.model_dump_json())
    assert isinstance(reloaded, ArrangementIRV2) and reloaded == value
    assert arrangement_content_hash(reloaded) != arrangement_content_hash(original)
    assert reloaded.tracks == original.tracks
    assert arrangement_content_hash(
        piano(events=(event(velocity_override=90),))
    ) != arrangement_content_hash(value)


def test_v2_performance_order_is_canonical_without_changing_score_order() -> None:
    a, b = event(5, velocity_override=72), event(6, gate_duration_tick=300)
    assert canonical_json_bytes(piano(events=(a, b))) == canonical_json_bytes(piano(events=(b, a)))


@pytest.mark.parametrize(
    "events,code",
    [
        ((event(999),), "PERFORMANCE_NOTE_NOT_FOUND"),
        ((event(), event()), "PERFORMANCE_NOTE_DUPLICATE"),
        ((event(onset_offset_tick=-1),), "PERFORMANCE_ONSET_OUT_OF_BOUNDS"),
        ((event(gate_duration_tick=1900),), "PERFORMANCE_GATE_OUT_OF_BOUNDS"),
    ],
)
def test_v2_rejects_dangling_duplicate_or_out_of_bounds_performance(events, code) -> None:
    with pytest.raises(ValueError, match=code):
        piano(events=events)


def test_unknown_ir_and_pedal_fail_closed() -> None:
    with pytest.raises(ValueError, match="IR_SCHEMA_VERSION_UNSUPPORTED"):
        read_arrangement_json(
            score().model_copy(update={"schema_version": "arrangement-ir.v999"}).model_dump_json()
        )
    with pytest.raises(ValueError, match="PIANO_PEDAL_UNSUPPORTED"):
        PerformancePlan.model_validate_json(
            '{"schema_version":"performance-plan.v1","pedal_events":[{"tick":0,"value":127}]}'
        )


def test_explicit_piano_command_existing_edits_and_inverse_keep_expression_and_version() -> None:
    from motif_forge.application.undo import build_inverse_commands
    from motif_forge.domain.commands import (
        Selection,
        SetPianoProfileCommand,
        SetPianoProfilePayload,
        SetTrackParamCommand,
        SetTrackParamPayload,
        apply_command,
    )
    from motif_forge.domain.policies import compute_change_impact
    from motif_forge.domain.revisions import ChangeImpact

    before = score()
    command = SetPianoProfileCommand(
        command_id=uid(100),
        actor_kind="human",
        client_sequence=0,
        selection=Selection(track_ids=(uid(3),)),
        payload=SetPianoProfilePayload(
            render_profile=PianoRenderProfile(),
            performance_plan=PerformancePlan(notes=(event(velocity_override=72),)),
        ),
    )
    upgraded = apply_command(before, command)
    assert isinstance(upgraded, ArrangementIRV2)
    assert compute_change_impact((command,)) is ChangeImpact.L2
    edited = apply_command(
        upgraded,
        SetTrackParamCommand(
            command_id=uid(101),
            actor_kind="human",
            client_sequence=0,
            payload=SetTrackParamPayload(track_id=uid(3), parameter="gain_db", value=-3.0),
        ),
    )
    assert (
        isinstance(edited, ArrangementIRV2) and edited.performance_plan == upgraded.performance_plan
    )
    inverse = build_inverse_commands(before, upgraded, (command,), actor_id="human")
    assert canonical_json_bytes(apply_command(upgraded, inverse[0])) == canonical_json_bytes(before)


def test_v2_projection_uses_pinned_piano_and_stable_event_order() -> None:
    from motif_forge.application.rendering import compile_audio_graph
    from motif_forge.domain.ir import ArrangementIRV2

    before = piano(
        events=(event(6, velocity_override=81), event(5, velocity_override=72, onset_offset_tick=8))
    )
    reversed_score = ArrangementIRV2.model_validate(
        {
            **before.model_dump(),
            "tracks": (
                before.tracks[0].model_copy(
                    update={
                        "clips": (
                            before.tracks[0]
                            .clips[0]
                            .model_copy(
                                update={"notes": tuple(reversed(before.tracks[0].clips[0].notes))}
                            ),
                        )
                    }
                ),
            ),
        }
    )
    projection = compile_audio_graph(before)
    assert projection.graph_hash == compile_audio_graph(reversed_score).graph_hash
    assert projection.graph["schemaVersion"] == "audio-graph-spec.v2"
    assert projection.graph["engineVersion"] == "motif-forge-audio-engine.v2"
    track = projection.graph["tracks"][0]
    assert track["kind"] == "multisample"
    assert track["instrumentPack"]["manifestSha256"] == before.render_profile.manifest_sha256
    assert track["notes"][0]["velocity"] == 72
    assert track["notes"][0]["startSeconds"] == round(8 / 480 / 2, 6)
    assert compile_audio_graph(score()).graph["tracks"][0]["kind"] == "synth"


def test_piano_jobs_and_export_plan_have_explicit_new_versions() -> None:
    from datetime import UTC, datetime

    from motif_forge.application.rendering import (
        build_candidate_preview_payload,
        build_canonical_render_payload,
    )
    from motif_forge.domain.export_plan import CompleteExportCursorV2, plan_export
    from motif_forge.domain.media_jobs import CandidatePreviewJobPayload, CanonicalRenderJobPayload
    from motif_forge.domain.revisions import (
        AuthorKind,
        ChangeImpact,
        Revision,
        create_candidate_snapshot,
        versions_for_arrangement,
    )

    value = piano(events=(event(velocity_override=72),))
    revision = Revision(
        revision_id=uid(30),
        project_id=uid(1),
        parent_revision_id=uid(31),
        created_on_branch_id=uid(32),
        arrangement_ir=value,
        content_hash=arrangement_content_hash(value),
        command_batch_id=uid(33),
        change_impact_predicted=ChangeImpact.L2,
        change_impact_actual=ChangeImpact.L2,
        author_kind=AuthorKind.HUMAN,
        created_by="human-test",
        reason_code="PIANO_FIXTURE",
        versions=versions_for_arrangement(value),
        created_at=datetime.now(UTC),
    )
    plan = plan_export(revision, seed=0, include_mp3=False, request_id=uid(34))
    assert (
        plan.schema_version == "export-plan.v3"
        and plan.engine_version == "motif-forge-audio-engine.v2"
    )
    cursor = CompleteExportCursorV2(
        plan=plan, plan_hash=plan.content_hash, thread_id="piano-export"
    )
    assert CompleteExportCursorV2.model_validate_json(cursor.model_dump_json()) == cursor
    payload = build_canonical_render_payload(revision, seed=0)
    assert (
        payload.schema_version == "canonical-render-job.v2"
        and payload.audio_engine_version == plan.engine_version
    )
    with pytest.raises(ValueError):
        CanonicalRenderJobPayload.model_validate_json(payload.model_dump_json())
    snapshot = create_candidate_snapshot(
        base_revision=revision,
        candidate_ir=value,
        candidate_id=uid(40),
        created_at=datetime.now(UTC),
    )
    preview = build_candidate_preview_payload(snapshot, seed=0)
    assert preview.schema_version == "candidate-preview-job.v2"
    with pytest.raises(ValueError):
        CandidatePreviewJobPayload.model_validate_json(preview.model_dump_json())


def test_fixed_piano_profile_rejects_silent_instrument_change_but_v1_keeps_chooser() -> None:
    from motif_forge.domain.commands import (
        SetTrackParamCommand,
        SetTrackParamPayload,
        apply_command,
    )
    from motif_forge.domain.errors import DomainValidationError

    change = SetTrackParamCommand(
        command_id=uid(201),
        actor_kind="human",
        client_sequence=0,
        payload=SetTrackParamPayload(
            track_id=uid(3), parameter="instrument_ref", value="builtin:viola"
        ),
    )
    assert apply_command(score(), change).tracks[0].instrument_ref == "builtin:viola"
    with pytest.raises(DomainValidationError, match="PIANO_INSTRUMENT_CHANGE_UNSUPPORTED"):
        apply_command(piano(), change)
