"""Typed editor commands and deterministic, side-effect-free command handlers."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from motif_forge.domain.errors import DomainIssue, DomainValidationError, issue
from motif_forge.domain.ir import (
    MAX_TRACKS,
    ArrangementIR,
    Articulation,
    AudioClip,
    Clip,
    DomainModel,
    NoteClip,
    NoteEvent,
    Track,
    TrackRole,
)

COMMAND_SCHEMA_VERSION = "editor-command.v1"


class Selection(DomainModel):
    track_ids: tuple[UUID, ...] = ()
    start_tick: int | None = Field(default=None, ge=0)
    end_tick: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (self.start_tick is None) != (self.end_tick is None):
            raise ValueError("selection start_tick and end_tick must be supplied together")
        if (
            self.start_tick is not None
            and self.end_tick is not None
            and self.end_tick <= self.start_tick
        ):
            raise ValueError("selection end_tick must be greater than start_tick")
        return self


class CommandEnvelope(DomainModel):
    command_id: UUID
    schema_version: Literal["editor-command.v1"] = "editor-command.v1"
    selection: Selection = Field(default_factory=Selection)
    actor_kind: Literal["human", "agent", "system"]
    client_sequence: int = Field(ge=0)


class AddTrackPayload(DomainModel):
    track: Track


class AddTrackCommand(CommandEnvelope):
    command_type: Literal["add_track"] = "add_track"
    payload: AddTrackPayload


class DeleteTrackPayload(DomainModel):
    track_id: UUID


class DeleteTrackCommand(CommandEnvelope):
    command_type: Literal["delete_track"] = "delete_track"
    payload: DeleteTrackPayload


class AddClipPayload(DomainModel):
    track_id: UUID
    clip: Clip


class AddClipCommand(CommandEnvelope):
    command_type: Literal["add_clip"] = "add_clip"
    payload: AddClipPayload


class ClipTargetPayload(DomainModel):
    track_id: UUID
    clip_id: UUID


class DeleteClipCommand(CommandEnvelope):
    command_type: Literal["delete_clip"] = "delete_clip"
    payload: ClipTargetPayload


class MoveClipPayload(ClipTargetPayload):
    start_tick: int = Field(ge=0)


class MoveClipCommand(CommandEnvelope):
    command_type: Literal["move_clip"] = "move_clip"
    payload: MoveClipPayload


class TrimClipPayload(ClipTargetPayload):
    start_tick: int = Field(ge=0)
    end_tick: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_tick <= self.start_tick:
            raise ValueError("trim end_tick must be greater than start_tick")
        return self


class TrimClipCommand(CommandEnvelope):
    command_type: Literal["trim_clip"] = "trim_clip"
    payload: TrimClipPayload


class SplitClipPayload(ClipTargetPayload):
    split_tick: int = Field(gt=0)
    right_clip_id: UUID


class SplitClipCommand(CommandEnvelope):
    command_type: Literal["split_clip"] = "split_clip"
    payload: SplitClipPayload


class SetTrackParamPayload(DomainModel):
    track_id: UUID
    parameter: Literal["name", "role", "mute", "solo", "gain_db", "pan", "instrument_ref"]
    value: str | bool | float | TrackRole

    @model_validator(mode="after")
    def validate_parameter_value(self) -> Self:
        value = self.value
        if self.parameter in {"mute", "solo"} and type(value) is not bool:
            raise ValueError(f"{self.parameter} requires a boolean value")
        if self.parameter in {"gain_db", "pan"} and type(value) is not float:
            raise ValueError(f"{self.parameter} requires a float value")
        if self.parameter in {"name", "instrument_ref"} and type(value) is not str:
            raise ValueError(f"{self.parameter} requires a string value")
        if self.parameter == "role" and not isinstance(value, TrackRole):
            raise ValueError("role requires a TrackRole value")
        return self


class SetTrackParamCommand(CommandEnvelope):
    command_type: Literal["set_track_param"] = "set_track_param"
    payload: SetTrackParamPayload


class SetClipParamPayload(ClipTargetPayload):
    parameter: Literal[
        "loop",
        "gain_db",
        "pan",
        "fade_in_tick",
        "fade_out_tick",
        "transpose_semitones",
    ]
    value: bool | int | float

    @model_validator(mode="after")
    def validate_parameter_value(self) -> Self:
        value = self.value
        if self.parameter == "loop" and type(value) is not bool:
            raise ValueError("loop requires a boolean value")
        if (
            self.parameter in {"fade_in_tick", "fade_out_tick", "transpose_semitones"}
            and type(value) is not int
        ):
            raise ValueError(f"{self.parameter} requires an integer value")
        if self.parameter in {"gain_db", "pan"} and type(value) is not float:
            raise ValueError(f"{self.parameter} requires a float value")
        return self


class SetClipParamCommand(CommandEnvelope):
    command_type: Literal["set_clip_param"] = "set_clip_param"
    payload: SetClipParamPayload


class AddNotesPayload(ClipTargetPayload):
    notes: tuple[NoteEvent, ...] = Field(min_length=1)


class AddNotesCommand(CommandEnvelope):
    command_type: Literal["add_notes"] = "add_notes"
    payload: AddNotesPayload


class NoteUpdate(DomainModel):
    note_id: UUID
    pitch: int | None = Field(default=None, ge=0, le=127)
    start_tick: int | None = Field(default=None, ge=0)
    duration_tick: int | None = Field(default=None, gt=0)
    velocity: int | None = Field(default=None, ge=1, le=127)
    articulation: Articulation | None = None
    cents: float | None = Field(default=None, ge=-100.0, le=100.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set.difference({"note_id"}):
            raise ValueError("note update must contain at least one changed field")
        return self


class UpdateNotesPayload(ClipTargetPayload):
    updates: tuple[NoteUpdate, ...] = Field(min_length=1)


class UpdateNotesCommand(CommandEnvelope):
    command_type: Literal["update_notes"] = "update_notes"
    payload: UpdateNotesPayload


class DeleteNotesPayload(ClipTargetPayload):
    note_ids: tuple[UUID, ...] = Field(min_length=1)


class DeleteNotesCommand(CommandEnvelope):
    command_type: Literal["delete_notes"] = "delete_notes"
    payload: DeleteNotesPayload


EditorCommand = Annotated[
    AddTrackCommand
    | DeleteTrackCommand
    | AddClipCommand
    | DeleteClipCommand
    | MoveClipCommand
    | TrimClipCommand
    | SplitClipCommand
    | SetTrackParamCommand
    | SetClipParamCommand
    | AddNotesCommand
    | UpdateNotesCommand
    | DeleteNotesCommand,
    Field(discriminator="command_type"),
]

EDITOR_COMMAND_ADAPTER: TypeAdapter[EditorCommand] = TypeAdapter(EditorCommand)


def _track_index(arrangement: ArrangementIR, track_id: UUID) -> int:
    for index, track in enumerate(arrangement.tracks):
        if track.track_id == track_id:
            return index
    raise issue("TRACK_NOT_FOUND", f"tracks.{track_id}", "track does not exist")


def _clip_index(track: Track, clip_id: UUID) -> int:
    for index, clip in enumerate(track.clips):
        if clip.clip_id == clip_id:
            return index
    raise issue("CLIP_NOT_FOUND", f"tracks.{track.track_id}.clips.{clip_id}", "clip does not exist")


def _intersects(start_tick: int, end_tick: int, other_start: int, other_end: int) -> bool:
    return start_tick < other_end and other_start < end_tick


def _assert_unlocked(track: Track, start_tick: int, end_tick: int) -> None:
    for locked in track.locked_ranges:
        if _intersects(start_tick, end_tick, locked.start_tick, locked.end_tick):
            raise issue(
                "LOCKED_RANGE_VIOLATION",
                f"tracks.{track.track_id}.locked_ranges",
                "command intersects locked material",
            )


def _rebuild_track(track: Track, **updates: Any) -> Track:
    data = track.model_dump(mode="python")
    data.update(updates)
    return Track.model_validate(data)


def _replace_track(arrangement: ArrangementIR, index: int, track: Track) -> ArrangementIR:
    tracks = list(arrangement.tracks)
    tracks[index] = track
    data = arrangement.model_dump(mode="python")
    data["tracks"] = tuple(tracks)
    return ArrangementIR.model_validate(data)


def _replace_clip(track: Track, index: int, *clips: Clip) -> Track:
    updated = list(track.clips)
    updated[index : index + 1] = clips
    return _rebuild_track(track, clips=tuple(updated))


def _note_clip(track: Track, clip_id: UUID) -> tuple[int, NoteClip]:
    index = _clip_index(track, clip_id)
    clip = track.clips[index]
    if not isinstance(clip, NoteClip):
        raise issue(
            "CLIP_TYPE_MISMATCH",
            f"tracks.{track.track_id}.clips.{clip_id}",
            "note command requires a note clip",
        )
    return index, clip


def _trim_note_clip(clip: NoteClip, start_tick: int, end_tick: int) -> NoteClip:
    local_start = start_tick - clip.start_tick
    local_end = end_tick - clip.start_tick
    notes: list[NoteEvent] = []
    for note in clip.notes:
        note_end = note.start_tick + note.duration_tick
        overlap_start = max(note.start_tick, local_start)
        overlap_end = min(note_end, local_end)
        if overlap_start >= overlap_end:
            continue
        data = note.model_dump(mode="python")
        data["start_tick"] = overlap_start - local_start
        data["duration_tick"] = overlap_end - overlap_start
        notes.append(NoteEvent.model_validate(data))
    data = clip.model_dump(mode="python")
    data.update(
        start_tick=start_tick,
        duration_tick=end_tick - start_tick,
        fade_in_tick=min(clip.fade_in_tick, end_tick - start_tick),
        fade_out_tick=min(clip.fade_out_tick, end_tick - start_tick),
        notes=tuple(notes),
    )
    if data["fade_in_tick"] + data["fade_out_tick"] > data["duration_tick"]:
        data["fade_out_tick"] = max(0, data["duration_tick"] - data["fade_in_tick"])
    return NoteClip.model_validate(data)


def _trim_audio_clip(clip: AudioClip, start_tick: int, end_tick: int) -> AudioClip:
    old_start = clip.start_tick
    old_duration = clip.duration_tick
    left_fraction = (start_tick - old_start) / old_duration
    kept_fraction = (end_tick - start_tick) / old_duration
    data = clip.model_dump(mode="python")
    data.update(
        start_tick=start_tick,
        duration_tick=end_tick - start_tick,
        source_offset_seconds=clip.source_offset_seconds
        + clip.source_duration_seconds * left_fraction,
        source_duration_seconds=clip.source_duration_seconds * kept_fraction,
        fade_in_tick=min(clip.fade_in_tick, end_tick - start_tick),
        fade_out_tick=min(clip.fade_out_tick, end_tick - start_tick),
    )
    if data["fade_in_tick"] + data["fade_out_tick"] > data["duration_tick"]:
        data["fade_out_tick"] = max(0, data["duration_tick"] - data["fade_in_tick"])
    return AudioClip.model_validate(data)


def _split_note_clip(
    clip: NoteClip, split_tick: int, right_clip_id: UUID, command_id: UUID
) -> tuple[NoteClip, NoteClip]:
    split_local = split_tick - clip.start_tick
    left_notes: list[NoteEvent] = []
    right_notes: list[NoteEvent] = []
    for note in clip.notes:
        note_end = note.start_tick + note.duration_tick
        if note_end <= split_local:
            left_notes.append(note)
        elif note.start_tick >= split_local:
            data = note.model_dump(mode="python")
            data["start_tick"] = note.start_tick - split_local
            right_notes.append(NoteEvent.model_validate(data))
        else:
            left_data = note.model_dump(mode="python")
            left_data["duration_tick"] = split_local - note.start_tick
            left_notes.append(NoteEvent.model_validate(left_data))
            right_data = note.model_dump(mode="python")
            right_data.update(
                note_id=uuid5(NAMESPACE_URL, f"{command_id}:{note.note_id}:right"),
                start_tick=0,
                duration_tick=note_end - split_local,
            )
            right_notes.append(NoteEvent.model_validate(right_data))

    left_data = clip.model_dump(mode="python")
    left_data.update(
        duration_tick=split_local,
        fade_in_tick=min(clip.fade_in_tick, split_local),
        fade_out_tick=0,
        notes=tuple(left_notes),
    )
    right_duration = clip.duration_tick - split_local
    right_data = clip.model_dump(mode="python")
    right_data.update(
        clip_id=right_clip_id,
        start_tick=split_tick,
        duration_tick=right_duration,
        fade_in_tick=0,
        fade_out_tick=min(clip.fade_out_tick, right_duration),
        notes=tuple(right_notes),
    )
    return NoteClip.model_validate(left_data), NoteClip.model_validate(right_data)


def _split_audio_clip(
    clip: AudioClip, split_tick: int, right_clip_id: UUID
) -> tuple[AudioClip, AudioClip]:
    split_local = split_tick - clip.start_tick
    left_fraction = split_local / clip.duration_tick
    left_source_duration = clip.source_duration_seconds * left_fraction
    left_data = clip.model_dump(mode="python")
    left_data.update(
        duration_tick=split_local,
        source_duration_seconds=left_source_duration,
        fade_in_tick=min(clip.fade_in_tick, split_local),
        fade_out_tick=0,
    )
    right_duration = clip.duration_tick - split_local
    right_data = clip.model_dump(mode="python")
    right_data.update(
        clip_id=right_clip_id,
        start_tick=split_tick,
        duration_tick=right_duration,
        source_offset_seconds=clip.source_offset_seconds + left_source_duration,
        source_duration_seconds=clip.source_duration_seconds - left_source_duration,
        fade_in_tick=0,
        fade_out_tick=min(clip.fade_out_tick, right_duration),
    )
    return AudioClip.model_validate(left_data), AudioClip.model_validate(right_data)


def _apply_command(arrangement: ArrangementIR, command: EditorCommand) -> ArrangementIR:
    # The discriminated command model guarantees the payload pairing at parse time. Pydantic's
    # plugin does not currently preserve that relationship when narrowing the union below.
    payload: Any = command.payload
    if isinstance(command, AddTrackCommand):
        if len(arrangement.tracks) >= MAX_TRACKS:
            raise issue("TRACK_LIMIT_EXCEEDED", "tracks", "v1 supports at most 12 tracks")
        data = arrangement.model_dump(mode="python")
        data["tracks"] = (*arrangement.tracks, payload.track)
        return ArrangementIR.model_validate(data)

    track_index = _track_index(arrangement, payload.track_id)
    track = arrangement.tracks[track_index]

    if isinstance(command, DeleteTrackCommand):
        if track.locked_ranges:
            raise issue(
                "LOCKED_RANGE_VIOLATION",
                f"tracks.{track.track_id}",
                "locked track cannot be deleted",
            )
        data = arrangement.model_dump(mode="python")
        data["tracks"] = tuple(
            item for item in arrangement.tracks if item.track_id != track.track_id
        )
        return ArrangementIR.model_validate(data)

    if isinstance(command, AddClipCommand):
        end_tick = payload.clip.start_tick + payload.clip.duration_tick
        _assert_unlocked(track, payload.clip.start_tick, end_tick)
        return _replace_track(
            arrangement,
            track_index,
            _rebuild_track(track, clips=(*track.clips, payload.clip)),
        )

    if isinstance(command, SetTrackParamCommand):
        if track.locked_ranges:
            raise issue(
                "LOCKED_RANGE_VIOLATION",
                f"tracks.{track.track_id}.locked_ranges",
                "track-wide parameters cannot change while material is locked",
            )
        changed_track = _rebuild_track(track, **{payload.parameter: payload.value})
        return _replace_track(arrangement, track_index, changed_track)

    clip_index = _clip_index(track, payload.clip_id)
    clip = track.clips[clip_index]
    clip_end = clip.start_tick + clip.duration_tick

    if isinstance(command, DeleteClipCommand):
        _assert_unlocked(track, clip.start_tick, clip_end)
        updated = tuple(item for item in track.clips if item.clip_id != clip.clip_id)
        return _replace_track(arrangement, track_index, _rebuild_track(track, clips=updated))

    if isinstance(command, MoveClipCommand):
        _assert_unlocked(track, clip.start_tick, clip_end)
        _assert_unlocked(track, payload.start_tick, payload.start_tick + clip.duration_tick)
        data = clip.model_dump(mode="python")
        data["start_tick"] = payload.start_tick
        moved = type(clip).model_validate(data)
        return _replace_track(arrangement, track_index, _replace_clip(track, clip_index, moved))

    if isinstance(command, TrimClipCommand):
        if payload.start_tick < clip.start_tick or payload.end_tick > clip_end:
            raise issue(
                "IR_RANGE_INVALID",
                f"tracks.{track.track_id}.clips.{clip.clip_id}",
                "trim range must remain inside the original clip",
            )
        _assert_unlocked(track, clip.start_tick, clip_end)
        trimmed = (
            _trim_note_clip(clip, payload.start_tick, payload.end_tick)
            if isinstance(clip, NoteClip)
            else _trim_audio_clip(clip, payload.start_tick, payload.end_tick)
        )
        return _replace_track(arrangement, track_index, _replace_clip(track, clip_index, trimmed))

    if isinstance(command, SplitClipCommand):
        if not clip.start_tick < payload.split_tick < clip_end:
            raise issue(
                "IR_RANGE_INVALID",
                f"tracks.{track.track_id}.clips.{clip.clip_id}",
                "split tick must be strictly inside the clip",
            )
        _assert_unlocked(track, payload.split_tick, payload.split_tick + 1)
        split = (
            _split_note_clip(clip, payload.split_tick, payload.right_clip_id, command.command_id)
            if isinstance(clip, NoteClip)
            else _split_audio_clip(clip, payload.split_tick, payload.right_clip_id)
        )
        return _replace_track(arrangement, track_index, _replace_clip(track, clip_index, *split))

    if isinstance(command, SetClipParamCommand):
        _assert_unlocked(track, clip.start_tick, clip_end)
        if payload.parameter == "transpose_semitones" and not isinstance(clip, AudioClip):
            raise issue(
                "CLIP_TYPE_MISMATCH",
                f"tracks.{track.track_id}.clips.{clip.clip_id}",
                "transpose_semitones is only available on audio clips in v1",
            )
        data = clip.model_dump(mode="python")
        data[payload.parameter] = payload.value
        changed = type(clip).model_validate(data)
        return _replace_track(arrangement, track_index, _replace_clip(track, clip_index, changed))

    note_clip_index, note_clip = _note_clip(track, payload.clip_id)

    if isinstance(command, AddNotesCommand):
        for note in payload.notes:
            _assert_unlocked(
                track,
                note_clip.start_tick + note.start_tick,
                note_clip.start_tick + note.start_tick + note.duration_tick,
            )
        data = note_clip.model_dump(mode="python")
        data["notes"] = (*note_clip.notes, *payload.notes)
        changed = NoteClip.model_validate(data)
    elif isinstance(command, UpdateNotesCommand):
        by_id = {note.note_id: note for note in note_clip.notes}
        for update in payload.updates:
            existing = by_id.get(update.note_id)
            if existing is None:
                raise issue(
                    "NOTE_NOT_FOUND",
                    f"tracks.{track.track_id}.clips.{note_clip.clip_id}.notes.{update.note_id}",
                    "note does not exist",
                )
            _assert_unlocked(
                track,
                note_clip.start_tick + existing.start_tick,
                note_clip.start_tick + existing.start_tick + existing.duration_tick,
            )
            note_data = existing.model_dump(mode="python")
            for field_name in update.model_fields_set.difference({"note_id"}):
                note_data[field_name] = getattr(update, field_name)
            by_id[update.note_id] = NoteEvent.model_validate(note_data)
        data = note_clip.model_dump(mode="python")
        data["notes"] = tuple(by_id[note.note_id] for note in note_clip.notes)
        changed = NoteClip.model_validate(data)
    elif isinstance(command, DeleteNotesCommand):
        existing_ids = {note.note_id for note in note_clip.notes}
        missing = set(payload.note_ids).difference(existing_ids)
        if missing:
            missing_id = min(missing, key=str)
            raise issue(
                "NOTE_NOT_FOUND",
                f"tracks.{track.track_id}.clips.{note_clip.clip_id}.notes.{missing_id}",
                "note does not exist",
            )
        for note in note_clip.notes:
            if note.note_id in payload.note_ids:
                _assert_unlocked(
                    track,
                    note_clip.start_tick + note.start_tick,
                    note_clip.start_tick + note.start_tick + note.duration_tick,
                )
        data = note_clip.model_dump(mode="python")
        data["notes"] = tuple(
            note for note in note_clip.notes if note.note_id not in payload.note_ids
        )
        changed = NoteClip.model_validate(data)
    else:  # pragma: no cover - exhaustive union safety
        raise TypeError(f"unsupported command: {type(command).__name__}")

    return _replace_track(
        arrangement,
        track_index,
        _replace_clip(track, note_clip_index, changed),
    )


def apply_command(arrangement: ArrangementIR, command: EditorCommand) -> ArrangementIR:
    """Apply one validated command and return a new immutable arrangement."""

    try:
        return _apply_command(arrangement, command)
    except DomainValidationError:
        raise
    except ValidationError as exc:
        raise issue("SCHEMA_INVALID", "arrangement_ir", str(exc)) from exc


def validate_command(arrangement: ArrangementIR, command: EditorCommand) -> tuple[DomainIssue, ...]:
    """Validate one command without mutating or returning project state."""

    try:
        apply_command(arrangement, command)
    except DomainValidationError as exc:
        return exc.issues
    return ()


def apply_commands(
    arrangement: ArrangementIR, commands: tuple[EditorCommand, ...]
) -> ArrangementIR:
    """Apply a command batch in stable sequence order."""

    command_ids: set[UUID] = set()
    sequences: set[int] = set()
    current = arrangement
    for command in commands:
        if command.command_id in command_ids:
            raise issue("SCHEMA_INVALID", "commands", "command_id must be unique in a batch")
        if command.client_sequence in sequences:
            raise issue("SCHEMA_INVALID", "commands", "client_sequence must be unique in a batch")
        command_ids.add(command.command_id)
        sequences.add(command.client_sequence)
        current = apply_command(current, command)
    return current


def validate_commands(
    arrangement: ArrangementIR, commands: tuple[EditorCommand, ...]
) -> tuple[DomainIssue, ...]:
    """Validate a dependent command batch using the same pure handler path."""

    try:
        apply_commands(arrangement, commands)
    except DomainValidationError as exc:
        return exc.issues
    return ()
