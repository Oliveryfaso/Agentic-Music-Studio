import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.piano_requests import PianoSemanticRequest


@pytest.mark.asyncio
async def test_saved_plan_replay_builds_identical_agent_commands_without_second_planner(
    monkeypatch,
):
    import motif_forge.application.piano_semantic as mod
    import motif_forge.resources.scores as scores
    from motif_forge.application.piano_preview import PianoPreviewRequest

    project, branch, revision, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    xml = Path(next(iter(scores.__path__))) / "ode-melody.musicxml"
    base = score_to_arrangement(
        parse_musicxml(xml.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    semantic = PianoSemanticRequest(intent="低音区,前8小节稀疏,后8小节活跃", mode="append")
    run = SimpleNamespace(
        project_id=project,
        branch_id=branch,
        base_revision_id=revision,
        run_id=run_id,
        edit_request={
            "intent": semantic.intent,
            "selection": {},
            "piano_request": semantic.model_dump(mode="json"),
        },
    )

    async def load(_thread):
        return run

    monkeypatch.setattr(mod, "ReadAIRunByThreadId", lambda _uow: load)

    class Store:
        record = None

        async def read(self, _run):
            return self.record

        async def save(self, _run, record):
            self.record = record
            return record

    store = Store()
    calls = []

    class Planner:
        async def create(self, b, req):
            calls.append(1)
            return {
                "schema_version": "piano-plan-record.v1",
                "model": "test-model",
                "usage": {"status": "known", "total_tokens": 300},
                "plan": {
                    "schema_version": "accompaniment-plan.v1",
                    "summary": "前疏后密",
                    "bars": [
                        {
                            "bar": i,
                            "chord": "G",
                            "grid": [0] if i < 9 else [0, 4, 8, 12],
                            "octave": 2,
                            "velocity": 48,
                        }
                        for i in range(1, 17)
                    ],
                },
            }

    request = PianoPreviewRequest(
        project_id=project,
        branch_id=branch,
        base_revision_id=revision,
        request_id=run_id,
        semantic=semantic,
    )
    first = await mod.PianoSemanticService(None, store, lambda r: Planner()).prepare(
        request, base, thread_id="thread-test"
    )

    def forbidden(_run):
        raise AssertionError("a stored result must not construct another paid planner")

    replay = await mod.PianoSemanticService(None, store, forbidden).prepare(
        request, base, thread_id="thread-test"
    )
    assert first == replay and calls == [1]
    assert first[0][0].actor_kind == "agent" and first[2] == run_id
    assert json.dumps(store.record, ensure_ascii=False).find("前疏后密") >= 0
