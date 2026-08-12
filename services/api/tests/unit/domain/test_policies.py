from uuid import UUID

from motif_forge.domain import (
    AddTrackCommand,
    AddTrackPayload,
    ChangeImpact,
    ImportAudioCommand,
    ImportAudioPayload,
    MoveClipCommand,
    MoveClipPayload,
    SetTrackParamCommand,
    SetTrackParamPayload,
    Track,
    TrackType,
    compute_change_impact,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


def command_fields(*, actor_kind: str = "human", sequence: int = 0) -> dict[str, object]:
    return {
        "command_id": uid(100 + sequence),
        "actor_kind": actor_kind,
        "client_sequence": sequence,
    }


def test_human_parameter_move_stays_l0() -> None:
    commands = (
        MoveClipCommand(
            payload=MoveClipPayload(track_id=uid(1), clip_id=uid(2), start_tick=480),
            **command_fields(),
        ),
        SetTrackParamCommand(
            payload=SetTrackParamPayload(track_id=uid(1), parameter="gain_db", value=-3.0),
            **command_fields(sequence=1),
        ),
    )

    assert compute_change_impact(commands) is ChangeImpact.L0


def test_human_structural_edit_is_l1_but_agent_creative_edit_escalates() -> None:
    track = Track(track_id=uid(1), track_type=TrackType.INSTRUMENT, name="Lead")
    human = AddTrackCommand(
        payload=AddTrackPayload(track=track),
        **command_fields(actor_kind="human"),
    )
    agent = AddTrackCommand(
        payload=AddTrackPayload(track=track),
        **command_fields(actor_kind="agent", sequence=1),
    )

    assert compute_change_impact((human,)) is ChangeImpact.L1
    assert compute_change_impact((human, agent)) is ChangeImpact.L2


def test_agent_main_timbre_replacement_requires_preview() -> None:
    command = SetTrackParamCommand(
        payload=SetTrackParamPayload(
            track_id=uid(1), parameter="instrument_ref", value="preset:new-lead"
        ),
        **command_fields(actor_kind="agent"),
    )

    assert compute_change_impact((command,)) is ChangeImpact.L2


def test_system_import_is_l1_but_agent_import_requires_preview() -> None:
    payload = ImportAudioPayload(
        track_id=uid(10),
        clip_id=uid(20),
        section_id=uid(30),
        artifact_id=uid(40),
        track_name="Imported Audio",
        duration_tick=960,
        source_duration_seconds=1.0,
    )
    system = ImportAudioCommand(payload=payload, **command_fields(actor_kind="system"))
    agent = ImportAudioCommand(payload=payload, **command_fields(actor_kind="agent", sequence=1))

    assert compute_change_impact((system,)) is ChangeImpact.L1
    assert compute_change_impact((agent,)) is ChangeImpact.L2
