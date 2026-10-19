"""Persist semantic plans before audition; deterministic commands own all mutations."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid5

from motif_forge.application.ai_runs import ReadAIRunByThreadId
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_harmony import require_preserved_harmony, resolve_piano_harmony
from motif_forge.application.ports import AIRunUnitOfWorkFactory, UnitOfWorkFactory
from motif_forge.domain.ai_runs import AIRun, EditRunRequest
from motif_forge.domain.commands import (
    AgentAppendPianoTrackCommand,
    AppendPianoTrackPayload,
    EditorCommand,
    ReplacePianoRangeCommand,
    ReplacePianoRangePayload,
    Selection,
    apply_commands,
)
from motif_forge.domain.ir import ArrangementIR
from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan

if TYPE_CHECKING:
    from motif_forge.application.piano_preview import PianoPreviewRequest


class PianoPlanStore(Protocol):
    async def read(self, run_id: UUID) -> dict[str, Any] | None: ...
    async def save(self, run_id: UUID, record: dict[str, Any]) -> dict[str, Any]: ...


class PianoPlanner(Protocol):
    async def create(
        self, base: ArrangementIR, request: Any, *, harmony: dict[int, str] | None = None
    ) -> dict[str, Any]: ...


class PianoSemanticService:
    def __init__(
        self,
        ai_uow: AIRunUnitOfWorkFactory,
        store: PianoPlanStore,
        planner_factory: Callable[[AIRun], PianoPlanner],
        *,
        projects: UnitOfWorkFactory | None = None,
    ) -> None:
        self.ai_uow, self._store, self._planner_factory = ai_uow, store, planner_factory
        self._projects = projects

    async def prepare(
        self, request: PianoPreviewRequest, base: ArrangementIR, *, thread_id: str
    ) -> tuple[tuple[EditorCommand, ...], dict[str, Any], UUID]:
        semantic = request.semantic
        if semantic is None:
            raise ApplicationError("PIANO_REQUEST_INVALID", "A semantic intent is required.")
        run = await ReadAIRunByThreadId(self.ai_uow)(thread_id)
        edit = EditRunRequest.model_validate_json(json.dumps(run.edit_request), strict=True)
        if (
            run.project_id != request.project_id
            or run.branch_id != request.branch_id
            or run.base_revision_id != request.base_revision_id
            or run.run_id != request.request_id
            or edit.piano_request != semantic
        ):
            raise ApplicationError(
                "PIANO_RUN_CONTEXT_MISMATCH", "Piano request does not match its durable AI Run."
            )
        # Validate authoritative target/scope before constructing a paid client.
        placeholder = AccompanimentPlan(
            summary="scope validation",
            bars=tuple(
                BarPlan(bar=i, chord="G", grid=(0,), octave=2, velocity=40)
                for i in range(semantic.start_bar, semantic.end_bar + 1)
            ),
        )
        compile_piano_plan(
            base,
            placeholder,
            request_id=run.run_id,
            target_track_id=semantic.target_track_id,
            start_bar=semantic.start_bar,
            end_bar=semantic.end_bar,
        )
        harmony = None
        if semantic.mode == "modify":
            if self._projects is None:
                raise ApplicationError(
                    "PIANO_HARMONY_UNVERIFIED", "A saved harmony recipe is required."
                )
            harmony = await resolve_piano_harmony(
                self._projects,
                self._store,
                revision_id=request.base_revision_id,
                base=base,
                start_bar=semantic.start_bar,
                end_bar=semantic.end_bar,
            )
        record = await self._store.read(run.run_id)
        if record is None:
            planner = self._planner_factory(run)
            record = (
                await planner.create(base, semantic)
                if harmony is None
                else await planner.create(base, semantic, harmony=harmony)
            )
            # Revalidate before persisting an immutable model result.
            plan = AccompanimentPlan.model_validate_json(json.dumps(record["plan"]), strict=True)
            compile_piano_plan(
                base,
                plan,
                request_id=run.run_id,
                target_track_id=semantic.target_track_id,
                start_bar=semantic.start_bar,
                end_bar=semantic.end_bar,
            )
            if harmony is not None:
                require_preserved_harmony(plan, harmony)
                record["harmony_policy"] = "piano-harmony-preserved.v1"
            record = await self._store.save(run.run_id, record)
        plan = AccompanimentPlan.model_validate_json(json.dumps(record["plan"]), strict=True)
        if harmony is not None:
            require_preserved_harmony(plan, harmony)
        track = compile_piano_plan(
            base,
            plan,
            request_id=run.run_id,
            target_track_id=semantic.target_track_id,
            start_bar=semantic.start_bar,
            end_bar=semantic.end_bar,
        )
        command: EditorCommand
        if semantic.mode == "append":
            command = AgentAppendPianoTrackCommand(
                command_id=uuid5(run.run_id, "semantic-append"),
                client_sequence=0,
                payload=AppendPianoTrackPayload(track=track),
            )
        else:
            command = ReplacePianoRangeCommand(
                command_id=uuid5(run.run_id, "semantic-range"),
                actor_kind="agent",
                client_sequence=0,
                selection=Selection(
                    track_ids=(track.track_id,),
                    start_tick=(semantic.start_bar - 1) * 1920,
                    end_tick=semantic.end_bar * 1920,
                ),
                payload=ReplacePianoRangePayload(
                    track=track, start_bar=semantic.start_bar, end_bar=semantic.end_bar
                ),
            )
        candidate = apply_commands(base, (command,))
        if candidate.tracks[0] != base.tracks[0]:
            raise ApplicationError(
                "ACCOMPANIMENT_ORIGINAL_CHANGED", "The original melody must remain identical."
            )
        # The shared render compiler checks the actual two-part profile and resource bounds.
        from motif_forge.application.rendering import compile_audio_graph

        compile_audio_graph(candidate)
        return (command,), record, run.run_id
