"""Prove saved octave parameters by replaying exact note identities and values."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_harmony import _notes
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.ir import ArrangementIR, NoteClip
from motif_forge.domain.piano_plan import PianoPlan, compile_piano_plan, read_piano_plan
from motif_forge.domain.piano_record import piano_source_metadata
from motif_forge.domain.piano_register import validate_preserved_register
from motif_forge.domain.reviewed_scores import reviewed_source


async def resolve_piano_register(
    projects: UnitOfWorkFactory,
    store: Any,
    *,
    revision_id: UUID,
    base: ArrangementIR,
    start_bar: int,
    end_bar: int,
) -> dict[int, int]:
    source = reviewed_source(base)
    if not 1 <= start_bar <= end_bar <= source.measures or end_bar - start_bar >= 4:
        raise ApplicationError("ACCOMPANIMENT_SCOPE_INVALID", "The source bar scope is invalid.")
    result: dict[int, int] = {}
    current_id: UUID | None = revision_id
    async with projects() as tx:
        for _ in range(64):
            if current_id is None:
                break
            revision = await tx.get_revision(current_id)
            if revision is None or revision.project_id != base.project_id:
                break
            matching = {
                bar
                for bar in range(start_bar, end_bar + 1)
                if bar not in result
                and _notes(base, bar)
                and _notes(base, bar) == _notes(revision.arrangement_ir, bar)
                and revision.arrangement_ir.tracks[1].track_id == base.tracks[1].track_id
            }
            if matching and revision.source_run_id is not None:
                record = await store.read(revision.source_run_id)
                if record is not None and (
                    record.get("source") == piano_source_metadata(source)
                    or (
                        record.get("schema_version") == "piano-plan-record.v1"
                        and source.score_id == "mutopia-528-melody.v1"
                    )
                ):
                    plan = read_piano_plan(json.dumps(record["plan"]))
                    for bar in plan.bars:
                        if bar.bar not in matching:
                            continue
                        single = plan.model_copy(update={"bars": (bar,)})
                        try:
                            replay = compile_piano_plan(
                                revision.arrangement_ir,
                                single,
                                request_id=revision.source_run_id,
                                target_track_id=base.tracks[1].track_id,
                                start_bar=bar.bar,
                                end_bar=bar.bar,
                            )
                        except ValueError:
                            continue
                        clip = replay.clips[0]
                        assert isinstance(clip, NoteClip)
                        notes = tuple(
                            n
                            for n in clip.notes
                            if (bar.bar - 1) * source.bar_ticks
                            <= n.start_tick
                            < bar.bar * source.bar_ticks
                        )
                        if notes == _notes(revision.arrangement_ir, bar.bar):
                            result[bar.bar] = bar.octave
            if len(result) == end_bar - start_bar + 1:
                return result
            current_id = revision.parent_revision_id
    raise ApplicationError(
        "PIANO_REGISTER_UNVERIFIED",
        "无法从保存计划核实所选伴奏音区,未调用模型。",
    )


def require_preserved_register(plan: PianoPlan, register: dict[int, int]) -> None:
    try:
        validate_preserved_register(plan, register)
    except ValueError as error:
        raise ApplicationError(
            "PIANO_REGISTER_CHANGED",
            "生成结果改变了要求保留的音区,已拒绝本次候选;原版本不变。",
        ) from error
