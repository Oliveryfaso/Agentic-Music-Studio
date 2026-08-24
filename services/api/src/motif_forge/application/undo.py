"""Append-only inverse Revision creation for committed editor batches."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import (
    ApplicationError,
    IdempotencyKeyReusedError,
    RevisionConflictError,
)
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import (
    AddClipCommand,
    AddClipPayload,
    AddNotesCommand,
    AddNotesPayload,
    AddTrackCommand,
    AddTrackPayload,
    DeleteClipCommand,
    DeleteNotesCommand,
    DeleteNotesPayload,
    DeleteTrackCommand,
    DeleteTrackPayload,
    DuplicateClipCommand,
    EditorCommand,
    ImportAudioCommand,
    InitializeCompositionCommand,
    MoveClipCommand,
    MoveClipPayload,
    NoteUpdate,
    SetClipParamCommand,
    SetClipParamPayload,
    SetTrackParamCommand,
    SetTrackParamPayload,
    SplitClipCommand,
    TrimClipCommand,
    UpdateNotesCommand,
    UpdateNotesPayload,
    apply_command,
    apply_commands,
)
from motif_forge.domain.ir import ArrangementIR, DomainModel, NoteClip, Track
from motif_forge.domain.policies import compute_change_impact
from motif_forge.domain.revisions import AuthorKind, ChangeImpact, Revision, VersionRefs

UNDO_REVISION_OPERATION = "revision.undo.v1"


class UndoCommittedRevisionRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    target_revision_id: UUID
    actor_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)


class UndoCommittedRevisionResult(DomainModel):
    project_id: UUID
    branch_id: UUID
    revision_id: UUID
    undone_revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_change_impact: ChangeImpact
    replayed: bool = False


def _track(arrangement: ArrangementIR, track_id: UUID) -> Track:
    found = next((item for item in arrangement.tracks if item.track_id == track_id), None)
    if found is None:
        raise ApplicationError("UNDO_NOT_AVAILABLE", "authoritative track facts are unavailable")
    return found


def _clip(arrangement: ArrangementIR, track_id: UUID, clip_id: UUID) -> Any:
    found = next(
        (item for item in _track(arrangement, track_id).clips if item.clip_id == clip_id),
        None,
    )
    if found is None:
        raise ApplicationError("UNDO_NOT_AVAILABLE", "authoritative clip facts are unavailable")
    return found


def _inverse_id(command_id: UUID, slot: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"motif-forge:undo:{command_id}:{slot}")


def _inverse_for(
    before: ArrangementIR,
    after: ArrangementIR,
    command: EditorCommand,
    *,
    first_sequence: int,
) -> tuple[EditorCommand, ...]:
    del after
    common = {"actor_kind": "human", "selection": command.selection}
    payload: Any = command.payload
    built: list[EditorCommand] = []

    def add(command_type: type[Any], inverse_payload: Any) -> None:
        slot = len(built)
        built.append(
            command_type(
                command_id=_inverse_id(command.command_id, slot),
                client_sequence=first_sequence + slot,
                payload=inverse_payload,
                **common,
            )
        )

    if isinstance(command, (InitializeCompositionCommand, ImportAudioCommand)):
        raise ApplicationError("UNDO_NOT_AVAILABLE", "this operation cannot be inverted")
    if isinstance(command, AddTrackCommand):
        add(DeleteTrackCommand, DeleteTrackPayload(track_id=payload.track.track_id))
    elif isinstance(command, DeleteTrackCommand):
        original = _track(before, payload.track_id)
        if before.tracks[-1].track_id != original.track_id:
            raise ApplicationError("UNDO_NOT_AVAILABLE", "track order cannot be restored safely")
        add(AddTrackCommand, AddTrackPayload(track=original))
    elif isinstance(command, AddClipCommand):
        add(DeleteClipCommand, {"track_id": payload.track_id, "clip_id": payload.clip.clip_id})
    elif isinstance(command, DeleteClipCommand):
        original = _clip(before, payload.track_id, payload.clip_id)
        if _track(before, payload.track_id).clips[-1].clip_id != original.clip_id:
            raise ApplicationError("UNDO_NOT_AVAILABLE", "clip order cannot be restored safely")
        add(AddClipCommand, AddClipPayload(track_id=payload.track_id, clip=original))
    elif isinstance(command, DuplicateClipCommand):
        add(
            DeleteClipCommand,
            {"track_id": payload.track_id, "clip_id": payload.duplicate_clip_id},
        )
    elif isinstance(command, MoveClipCommand):
        original = _clip(before, payload.track_id, payload.clip_id)
        add(
            MoveClipCommand,
            MoveClipPayload(
                track_id=payload.track_id,
                clip_id=payload.clip_id,
                start_tick=original.start_tick,
            ),
        )
    elif isinstance(command, TrimClipCommand):
        original = _clip(before, payload.track_id, payload.clip_id)
        add(DeleteClipCommand, {"track_id": payload.track_id, "clip_id": payload.clip_id})
        add(AddClipCommand, AddClipPayload(track_id=payload.track_id, clip=original))
    elif isinstance(command, SplitClipCommand):
        original = _clip(before, payload.track_id, payload.clip_id)
        add(DeleteClipCommand, {"track_id": payload.track_id, "clip_id": payload.clip_id})
        add(DeleteClipCommand, {"track_id": payload.track_id, "clip_id": payload.right_clip_id})
        add(AddClipCommand, AddClipPayload(track_id=payload.track_id, clip=original))
    elif isinstance(command, SetTrackParamCommand):
        original = _track(before, payload.track_id)
        value = (
            getattr(original.eq, payload.parameter.removeprefix("eq_"))
            if payload.parameter.startswith("eq_")
            else getattr(original, payload.parameter)
        )
        add(
            SetTrackParamCommand,
            SetTrackParamPayload(
                track_id=payload.track_id, parameter=payload.parameter, value=value
            ),
        )
    elif isinstance(command, SetClipParamCommand):
        original = _clip(before, payload.track_id, payload.clip_id)
        add(
            SetClipParamCommand,
            SetClipParamPayload(
                track_id=payload.track_id,
                clip_id=payload.clip_id,
                parameter=payload.parameter,
                value=getattr(original, payload.parameter),
            ),
        )
    elif isinstance(command, AddNotesCommand):
        add(
            DeleteNotesCommand,
            DeleteNotesPayload(
                track_id=payload.track_id,
                clip_id=payload.clip_id,
                note_ids=tuple(note.note_id for note in payload.notes),
            ),
        )
    elif isinstance(command, DeleteNotesCommand):
        original = _clip(before, payload.track_id, payload.clip_id)
        if not isinstance(original, NoteClip):
            raise ApplicationError("UNDO_NOT_AVAILABLE", "note facts are unavailable")
        note_ids = set(payload.note_ids)
        add(
            AddNotesCommand,
            AddNotesPayload(
                track_id=payload.track_id,
                clip_id=payload.clip_id,
                notes=tuple(note for note in original.notes if note.note_id in note_ids),
            ),
        )
    elif isinstance(command, UpdateNotesCommand):
        original = _clip(before, payload.track_id, payload.clip_id)
        if not isinstance(original, NoteClip):
            raise ApplicationError("UNDO_NOT_AVAILABLE", "note facts are unavailable")
        by_id = {note.note_id: note for note in original.notes}
        updates = tuple(
            NoteUpdate(**by_id[item.note_id].model_dump(mode="python")) for item in payload.updates
        )
        add(
            UpdateNotesCommand,
            UpdateNotesPayload(
                track_id=payload.track_id, clip_id=payload.clip_id, updates=updates
            ),
        )
    else:
        raise ApplicationError("UNDO_NOT_AVAILABLE", "unsupported inverse command")
    return tuple(built)


def build_inverse_commands(
    parent: ArrangementIR,
    committed: ArrangementIR,
    commands: tuple[EditorCommand, ...],
    *,
    actor_id: str,
) -> tuple[EditorCommand, ...]:
    del actor_id
    facts: list[tuple[ArrangementIR, ArrangementIR, EditorCommand]] = []
    current = parent
    for command in commands:
        next_state = apply_command(current, command)
        facts.append((current, next_state, command))
        current = next_state
    if current != committed:
        raise ApplicationError("UNDO_NOT_AVAILABLE", "stored commands do not reproduce Revision")
    inverse: list[EditorCommand] = []
    for before, after, command in reversed(facts):
        inverse.extend(_inverse_for(before, after, command, first_sequence=len(inverse)))
    if apply_commands(committed, tuple(inverse)) != parent:
        raise ApplicationError("UNDO_NOT_AVAILABLE", "inverse commands do not restore parent")
    return tuple(inverse)


class UndoCommittedRevision:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        versions: VersionRefs | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock
        self._versions = versions or VersionRefs()

    async def __call__(self, request: UndoCommittedRevisionRequest) -> UndoCommittedRevisionResult:
        fingerprint = request_hash(
            {
                "schema": UNDO_REVISION_OPERATION,
                **request.model_dump(mode="json", exclude={"idempotency_key"}),
            }
        )
        async with self._uow_factory() as transaction:
            hit = await transaction.get_idempotency(
                operation=UNDO_REVISION_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return UndoCommittedRevisionResult.model_validate_json(
                    json.dumps({**hit.result_payload, "replayed": True})
                )
            branch = await transaction.lock_branch(
                project_id=request.project_id, branch_id=request.branch_id
            )
            if branch is None:
                raise ApplicationError("BRANCH_NOT_FOUND", "target branch does not exist")
            if branch.head_revision_id != request.base_revision_id:
                raise RevisionConflictError(branch.head_revision_id)
            target = await transaction.get_revision(request.target_revision_id)
            if target is None or target.project_id != request.project_id:
                raise ApplicationError("REVISION_NOT_FOUND", "target Revision does not exist")
            if target.parent_revision_id is None:
                raise ApplicationError("UNDO_NOT_AVAILABLE", "root Revision cannot be undone")
            parent = await transaction.get_revision(target.parent_revision_id)
            if parent is None or parent.project_id != request.project_id:
                raise ApplicationError("UNDO_NOT_AVAILABLE", "parent Revision is unavailable")
            commands = await transaction.list_revision_commands(target.revision_id)
            if not commands:
                raise ApplicationError("UNDO_NOT_AVAILABLE", "Revision has no invertible commands")
            inverse = build_inverse_commands(
                parent.arrangement_ir,
                target.arrangement_ir,
                commands,
                actor_id=request.actor_id,
            )
            candidate = apply_commands(target.arrangement_ir, inverse)
            impact = compute_change_impact(inverse)
            if impact >= ChangeImpact.L2:
                raise ApplicationError(
                    "UNDO_NOT_AVAILABLE", "inverse impact is not auto-committable"
                )
            batch_id = self._id_factory()
            revision = Revision(
                revision_id=self._id_factory(),
                project_id=request.project_id,
                parent_revision_id=request.base_revision_id,
                created_on_branch_id=request.branch_id,
                arrangement_ir=candidate,
                content_hash=arrangement_content_hash(candidate),
                command_batch_id=batch_id,
                change_impact_predicted=impact,
                change_impact_actual=impact,
                author_kind=AuthorKind.HUMAN,
                created_by=request.actor_id,
                reason_code="HUMAN_UNDO",
                versions=self._versions,
                created_at=self._clock(),
            )
            await transaction.insert_revision(
                revision=revision, commands=inverse, idempotency_key=request.idempotency_key
            )
            if not await transaction.advance_branch_head(
                branch_id=request.branch_id,
                expected_head_id=request.base_revision_id,
                new_head_id=revision.revision_id,
            ):
                raise RevisionConflictError(request.base_revision_id)
            await transaction.insert_audit_event(
                event_id=self._id_factory(),
                project_id=request.project_id,
                actor_id=request.actor_id,
                event_type="project.revision.undone",
                resource_id=revision.revision_id,
                payload={"undone_revision_id": str(request.target_revision_id)},
            )
            result = UndoCommittedRevisionResult(
                project_id=request.project_id,
                branch_id=request.branch_id,
                revision_id=revision.revision_id,
                undone_revision_id=request.target_revision_id,
                content_hash=revision.content_hash,
                actual_change_impact=impact,
            )
            await transaction.save_idempotency(
                operation=UNDO_REVISION_OPERATION,
                key=request.idempotency_key,
                request_hash=fingerprint,
                resource_id=revision.revision_id,
                result_payload=result.model_dump(mode="json", exclude={"replayed"}),
            )
            return result
