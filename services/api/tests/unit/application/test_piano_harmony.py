from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from motif_forge.application.errors import ApplicationError
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import (
    AgentAppendPianoTrackCommand,
    AppendPianoTrackPayload,
    ReplacePianoRangeCommand,
    ReplacePianoRangePayload,
    Selection,
    apply_commands,
)
from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan


def fixture():
    import motif_forge.resources.scores as scores

    project = uuid4()
    xml = Path(next(iter(scores.__path__))) / "ode-melody.musicxml"
    source = score_to_arrangement(
        parse_musicxml(xml.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    plan = AccompanimentPlan(
        summary="original harmony",
        bars=tuple(
            BarPlan(
                bar=i,
                chord=("G", "C", "D", "Em")[(i - 1) % 4],
                grid=(0, 4, 8, 12),
                octave=2,
                velocity=54,
            )
            for i in range(1, 17)
        ),
    )
    run1, run2, rev1, rev2, rev3 = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    track = compile_piano_plan(source, plan, request_id=run1)
    base = apply_commands(
        source,
        (
            AgentAppendPianoTrackCommand(
                command_id=uuid4(), client_sequence=0, payload=AppendPianoTrackPayload(track=track)
            ),
        ),
    )
    part = AccompanimentPlan(
        summary="quieter range",
        bars=tuple(
            BarPlan(bar=i, chord=plan.bars[i - 1].chord, grid=(0,), octave=2, velocity=40)
            for i in range(9, 13)
        ),
    )
    updated = compile_piano_plan(
        base, part, request_id=run2, target_track_id=track.track_id, start_bar=9, end_bar=12
    )
    second = apply_commands(
        base,
        (
            ReplacePianoRangeCommand(
                command_id=uuid4(),
                client_sequence=0,
                actor_kind="agent",
                selection=Selection(track_ids=(track.track_id,), start_tick=15360, end_tick=23040),
                payload=ReplacePianoRangePayload(track=updated, start_bar=9, end_bar=12),
            ),
        ),
    )
    revisions = {
        rev1: SimpleNamespace(
            revision_id=rev1,
            project_id=project,
            source_run_id=run1,
            parent_revision_id=None,
            arrangement_ir=base,
        ),
        rev2: SimpleNamespace(
            revision_id=rev2,
            project_id=project,
            source_run_id=run2,
            parent_revision_id=rev1,
            arrangement_ir=second,
        ),
        rev3: SimpleNamespace(
            revision_id=rev3,
            project_id=project,
            source_run_id=None,
            parent_revision_id=rev2,
            arrangement_ir=base,
        ),
    }

    class Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get_revision(self, id):
            return revisions[id]

        async def list_revision_commands(self, id):
            return ()

    class Store:
        async def read(self, id):
            return {"plan": (plan if id == run1 else part).model_dump(mode="json")}

    return Tx, Store(), revisions, rev1, rev2, rev3, plan


@pytest.mark.asyncio
async def test_harmony_is_verified_from_exact_saved_notes_across_other_range_edits_and_undo():
    from motif_forge.application.piano_harmony import resolve_piano_harmony

    tx, store, revisions, _r1, r2, r3, plan = fixture()
    for revision, start, end in ((r2, 1, 4), (r3, 9, 12)):
        harmony = await resolve_piano_harmony(
            tx,
            store,
            revision_id=revision,
            base=revisions[revision].arrangement_ir,
            start_bar=start,
            end_bar=end,
        )
        assert harmony == {i: plan.bars[i - 1].chord for i in range(start, end + 1)}


@pytest.mark.asyncio
async def test_unverifiable_current_bar_fails_before_a_paid_planner_can_be_built():
    from motif_forge.application.piano_harmony import resolve_piano_harmony

    tx, store, revisions, _r1, _r2, r3, _plan = fixture()
    base = revisions[r3].arrangement_ir
    target = base.tracks[1]
    clip = target.clips[0]
    altered = clip.notes[0].model_copy(update={"velocity": 53})
    clip = clip.model_copy(update={"notes": (altered, *clip.notes[1:])})
    changed = base.model_copy(
        update={"tracks": (base.tracks[0], target.model_copy(update={"clips": (clip,)}))}
    )
    with pytest.raises(ApplicationError, match="verified"):
        await resolve_piano_harmony(tx, store, revision_id=r3, base=changed, start_bar=1, end_bar=4)


def test_model_chord_changes_are_rejected_instead_of_silently_clamped():
    from motif_forge.application.piano_harmony import require_preserved_harmony

    *_, plan = fixture()
    with pytest.raises(ApplicationError, match="harmony"):
        require_preserved_harmony(
            AccompanimentPlan(summary="local", bars=plan.bars[8:12]),
            {9: "C", 10: "C", 11: "D", 12: "Em"},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("pattern", ["roots", "broken"])
async def test_recorded_human_p21_recipe_remains_a_valid_harmony_source(pattern):
    import motif_forge.resources.scores as scores
    from motif_forge.application.piano_harmony import resolve_piano_harmony
    from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command

    project = uuid4()
    xml = Path(next(iter(scores.__path__))) / "ode-melody.musicxml"
    source = score_to_arrangement(
        parse_musicxml(xml.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    chords = ("G", "C", "D", "Em") * 4
    command = accompaniment_command(
        source, AccompanimentIntent(pattern=pattern, chords=chords), request_id=uuid4()
    )
    base = apply_commands(source, (command,))
    revision_id = uuid4()
    revision = SimpleNamespace(
        revision_id=revision_id,
        project_id=project,
        source_run_id=None,
        parent_revision_id=None,
        arrangement_ir=base,
    )

    class Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get_revision(self, _):
            return revision

        async def list_revision_commands(self, _):
            return (command,)

    class Store:
        async def read(self, _):
            raise AssertionError("human recipes do not invent an AI plan")

    assert await resolve_piano_harmony(
        Tx, Store(), revision_id=revision_id, base=base, start_bar=9, end_bar=12
    ) == {i: chords[i - 1] for i in range(9, 13)}


@pytest.mark.asyncio
async def test_service_checks_returned_chords_before_persisting_or_creating_candidate(monkeypatch):
    import motif_forge.application.piano_semantic as service
    from motif_forge.application.piano_preview import PianoPreviewRequest
    from motif_forge.domain.piano_requests import PianoSemanticRequest

    tx, old_store, revisions, r1, _r2, _r3, original_plan = fixture()
    base = revisions[r1].arrangement_ir
    run_id = uuid4()
    branch = uuid4()
    semantic = PianoSemanticRequest(
        intent="更疏更轻",
        mode="modify",
        target_track_id=base.tracks[1].track_id,
        start_bar=9,
        end_bar=12,
    )
    run = SimpleNamespace(
        project_id=base.project_id,
        branch_id=branch,
        base_revision_id=r1,
        run_id=run_id,
        edit_request={
            "intent": semantic.intent,
            "selection": {
                "track_ids": [str(base.tracks[1].track_id)],
                "start_tick": 15360,
                "end_tick": 23040,
            },
            "piano_request": semantic.model_dump(mode="json"),
        },
    )

    async def load(_):
        return run

    monkeypatch.setattr(service, "ReadAIRunByThreadId", lambda _: load)

    class Store:
        async def read(self, id):
            return None if id == run_id else await old_store.read(id)

        async def save(self, *_):
            raise AssertionError("bad harmony must not be persisted")

    calls = []

    class Planner:
        async def create(self, base, request, *, harmony=None):
            calls.append(1)
            assert harmony == {i: original_plan.bars[i - 1].chord for i in range(9, 13)}
            return {
                "plan": AccompanimentPlan(
                    summary="unrequested reharmonization",
                    bars=tuple(
                        BarPlan(bar=i, chord="Em", grid=(0,), octave=2, velocity=40)
                        for i in range(9, 13)
                    ),
                ).model_dump(mode="json")
            }

    request = PianoPreviewRequest(
        project_id=base.project_id,
        branch_id=branch,
        base_revision_id=r1,
        request_id=run_id,
        semantic=semantic,
    )
    with pytest.raises(ApplicationError, match="harmony"):
        await service.PianoSemanticService(None, Store(), lambda _: Planner(), projects=tx).prepare(
            request, base, thread_id="test"
        )
    assert calls == [1]
