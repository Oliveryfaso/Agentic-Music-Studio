"""Explicit, self-authored study creation, with no model or imported composition."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, IdempotencyKeyReusedError
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import (
    AddTrackCommand,
    AddTrackPayload,
    EditorCommand,
    InitializeCompositionCommand,
    InitializeCompositionPayload,
    apply_commands,
)
from motif_forge.domain.ir import (
    DomainModel,
    KeyPoint,
    MeterPoint,
    MusicalMode,
    NoteClip,
    NoteEvent,
    ProvenanceRef,
    Section,
    TempoPoint,
    Track,
    TrackType,
)
from motif_forge.domain.revisions import AuthorKind, ChangeImpact, Revision


class PianoStudyRequest(DomainModel):
    name: str = Field(default="Piano study", min_length=1, max_length=120)


class PianoStudyResult(DomainModel):
    project_id: UUID
    branch_id: UUID
    revision_id: UUID
    content_hash: str
    replayed: bool = False


def study_commands(project_id: UUID) -> tuple[EditorCommand, ...]:
    def ident(name: str) -> UUID:
        return uuid5(project_id, "piano-study.v1:" + name)

    chords = ((60, 64, 67, 72), (57, 60, 64, 69), (53, 57, 60, 65), (55, 59, 62, 67))
    notes = tuple(
        NoteEvent(
            note_id=ident(f"note:{bar}:{i}"),
            pitch=chords[bar % 4][(0, 1, 2, 3, 2, 1, 2, 1)[i]],
            start_tick=bar * 1920 + i * 240,
            duration_tick=180,
            velocity=92,
        )
        for bar in range(12)
        for i in range(8)
    )
    return (
        InitializeCompositionCommand(
            command_id=ident("init"),
            actor_kind="system",
            client_sequence=0,
            payload=InitializeCompositionPayload(
                tempo=TempoPoint(bpm=128.0),
                meter=MeterPoint(),
                key_map=(
                    KeyPoint(
                        tick=0,
                        tonic="C",
                        mode=MusicalMode.MAJOR,
                        confidence=1.0,
                        source="self-authored",
                    ),
                ),
                sections=(
                    Section(
                        section_id=ident("section"),
                        start_tick=0,
                        end_tick=30720,
                        label="Arpeggio study and rest",
                    ),
                ),
                provenance=(
                    ProvenanceRef(kind="human", ref="self-authored:piano-study.v1", version="1"),
                ),
            ),
        ),
        AddTrackCommand(
            command_id=ident("add-track"),
            actor_kind="system",
            client_sequence=1,
            payload=AddTrackPayload(
                track=Track(
                    track_id=ident("track"),
                    track_type=TrackType.INSTRUMENT,
                    name="Study piano",
                    instrument_ref="builtin:jazz-piano",
                    clips=(
                        NoteClip(
                            clip_id=ident("clip"), start_tick=0, duration_tick=30720, notes=notes
                        ),
                    ),
                )
            ),
        ),
    )


class CreatePianoStudy:
    def __init__(self, projects: UnitOfWorkFactory) -> None:
        self._projects = projects

    async def __call__(
        self, request: PianoStudyRequest, *, idempotency_key: str
    ) -> PianoStudyResult:
        key = "piano-study:" + sha256(idempotency_key.encode()).hexdigest()
        fingerprint = request_hash(request.model_dump(mode="json"))
        project = await CreateProject(self._projects)(
            CreateProjectRequest(name=request.name, actor_id="human:local", idempotency_key=key)
        )
        async with self._projects() as tx:
            branch = await tx.lock_branch(
                project_id=project.project_id, branch_id=project.active_branch_id
            )
            hit = await tx.get_idempotency(
                operation="piano-study.v1", key=key, request_hash=fingerprint
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return PianoStudyResult.model_validate_json(
                    json.dumps({**hit.result_payload, "replayed": True}), strict=True
                )
            if branch is None or branch.head_revision_id != project.root_revision_id:
                raise ApplicationError(
                    "REVISION_CONFLICT", "The new study root has already changed."
                )
            root = await tx.get_revision(project.root_revision_id)
            assert root is not None
            commands = study_commands(project.project_id)
            score = apply_commands(root.arrangement_ir, commands)
            revision = Revision(
                revision_id=uuid5(project.project_id, "piano-study-revision.v1"),
                project_id=project.project_id,
                parent_revision_id=root.revision_id,
                created_on_branch_id=project.active_branch_id,
                arrangement_ir=score,
                content_hash=arrangement_content_hash(score),
                command_batch_id=uuid4(),
                change_impact_predicted=ChangeImpact.L2,
                change_impact_actual=ChangeImpact.L2,
                author_kind=AuthorKind.SYSTEM,
                created_by="system:self-authored-study",
                reason_code="SELF_AUTHORED_PIANO_STUDY",
                created_at=datetime.now(UTC),
            )
            await tx.insert_revision(revision=revision, commands=commands, idempotency_key=key)
            if not await tx.advance_branch_head(
                branch_id=project.active_branch_id,
                expected_head_id=root.revision_id,
                new_head_id=revision.revision_id,
            ):
                raise ApplicationError(
                    "REVISION_CONFLICT", "The new study root has already changed."
                )
            await tx.insert_audit_event(
                event_id=uuid4(),
                project_id=project.project_id,
                actor_id="human:local",
                event_type="project.piano-study.created",
                resource_id=revision.revision_id,
                payload={"provenance": "self-authored:piano-study.v1", "model_calls": 0},
            )
            result = PianoStudyResult(
                project_id=project.project_id,
                branch_id=project.active_branch_id,
                revision_id=revision.revision_id,
                content_hash=revision.content_hash,
            )
            await tx.save_idempotency(
                operation="piano-study.v1",
                key=key,
                request_hash=fingerprint,
                resource_id=revision.revision_id,
                result_payload=result.model_dump(mode="json"),
            )
            return result
