"""Versioned deterministic policies for domain-level routing decisions."""

from __future__ import annotations

from motif_forge.domain.commands import (
    AddClipCommand,
    AddNotesCommand,
    AddTrackCommand,
    DeleteClipCommand,
    DeleteNotesCommand,
    DeleteTrackCommand,
    EditorCommand,
    ImportAudioCommand,
    InitializeCompositionCommand,
    SetClipParamCommand,
    SetTrackParamCommand,
    UpdateNotesCommand,
)
from motif_forge.domain.revisions import ChangeImpact

CHANGE_IMPACT_POLICY_VERSION = "change-impact.v1"


def command_change_impact(command: EditorCommand) -> ChangeImpact:
    """Classify one already-validated editor command conservatively.

    The command actor is authoritative input: an agent proposing creative material is
    escalated even when the same explicit gesture would be a bounded human edit.
    """

    if isinstance(command, InitializeCompositionCommand):
        return ChangeImpact.L3

    if isinstance(command, SetTrackParamCommand):
        if command.payload.parameter in {"mute", "solo", "gain_db", "pan"}:
            return ChangeImpact.L0
        if command.actor_kind == "agent" and command.payload.parameter == "instrument_ref":
            return ChangeImpact.L2
        return ChangeImpact.L1

    if isinstance(command, SetClipParamCommand):
        if command.payload.parameter in {
            "loop",
            "gain_db",
            "pan",
            "fade_in_tick",
            "fade_out_tick",
        }:
            return ChangeImpact.L0
        return ChangeImpact.L1

    creative_commands = (
        AddTrackCommand,
        ImportAudioCommand,
        DeleteTrackCommand,
        AddClipCommand,
        DeleteClipCommand,
        AddNotesCommand,
        UpdateNotesCommand,
        DeleteNotesCommand,
    )
    if command.actor_kind == "agent" and isinstance(command, creative_commands):
        return ChangeImpact.L2

    if isinstance(command, creative_commands):
        return ChangeImpact.L1

    return ChangeImpact.L0


def compute_change_impact(commands: tuple[EditorCommand, ...]) -> ChangeImpact:
    """Return the maximum impact for a command batch without model judgment."""

    return max((command_change_impact(command) for command in commands), default=ChangeImpact.L0)
