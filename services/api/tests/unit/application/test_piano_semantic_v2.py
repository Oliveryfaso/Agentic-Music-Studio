import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from motif_forge.application.classical_import import reviewed_score
from motif_forge.application.piano_preview import PianoPreviewRequest
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.piano_requests import PianoSemanticRequest, PianoSemanticRequestV2
from motif_forge.infrastructure.persistence.piano_plans import _copy_record
from motif_forge.providers.deepseek import DeepSeekJsonClient
from motif_forge.providers.piano import DeepSeekPianoPlanner


def fixture(score, beats, bars):
    project = uuid4()
    _, xml = reviewed_score(score)
    base = score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref="score:" + score
    )
    request = PianoSemanticRequestV2(
        source_score_id=score,
        beats_per_bar=beats,
        end_bar=bars,
        mode="append",
        intent="前半稀疏,后半稍活跃,保持旋律",
    )
    return base, request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "score,beats,bars,chord",
    [
        ("c01-minuet-g-a16.v1", 3, 16, "G"),
        ("c02-la-candeur-a8.v1", 4, 8, "F"),
        ("j01-bethena-a-first8.v1", 3, 8, "G"),
    ],
)
async def test_new_provider_context_record_and_restart_replay_are_source_bound(
    monkeypatch, score, beats, bars, chord
):
    import motif_forge.application.piano_semantic as service

    base, semantic = fixture(score, beats, bars)
    run = SimpleNamespace(
        project_id=base.project_id,
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        run_id=uuid4(),
        edit_request={
            "intent": semantic.intent,
            "selection": {},
            "piano_request": semantic.model_dump(mode="json"),
        },
    )

    async def load(_):
        return run

    monkeypatch.setattr(service, "ReadAIRunByThreadId", lambda _: load)
    calls = []

    async def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        context = json.loads(body["messages"][1]["content"])["context"]
        assert context["source_score_id"] == score
        assert context["meter"] == f"{beats}/4" and context["bar_ticks"] == beats * 480
        assert context["source_measures"] == bars and context["key"] == (
            "C major" if chord == "F" else "G major"
        )
        assert max(n[0] for n in context["melody"]) == bars
        assert ("F" in context["allowed_chords"]) == (chord == "F")
        assert body["max_tokens"] == 3072 and "tools" not in body
        plan = {
            "schema_version": "accompaniment-plan.v2",
            "beats_per_bar": beats,
            "summary": "疏密对比",
            "bars": [
                {
                    "bar": i,
                    "chord": chord,
                    "grid": [0] if i <= bars // 2 else list(range(0, beats * 4, 4)),
                    "octave": 2,
                    "velocity": 48,
                    "gate_steps": 3,
                }
                for i in range(1, bars + 1)
            ],
        }
        return httpx.Response(
            200,
            json={
                "model": "offline-fixture",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"supported": True, "reason": "支持", "plan": plan}
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            },
        )

    class Store:
        record = None

        async def read(self, _):
            return self.record

        async def save(self, _, record):
            self.record = _copy_record(record)
            return self.record

    store = Store()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        planner = DeepSeekPianoPlanner(
            DeepSeekJsonClient(api_key="mock-only", http_client=http, max_attempts=1)
        )
        req = PianoPreviewRequest(
            project_id=run.project_id,
            branch_id=run.branch_id,
            base_revision_id=run.base_revision_id,
            request_id=run.run_id,
            semantic=semantic,
        )
        first = await service.PianoSemanticService(None, store, lambda _: planner).prepare(
            req, base, thread_id="v2"
        )

    def forbidden(_):
        raise AssertionError("replay must not construct a paid client")

    assert (
        await service.PianoSemanticService(None, store, forbidden).prepare(
            req, base, thread_id="v2"
        )
        == first
    )
    assert len(calls) == 1
    assert store.record["schema_version"] == "piano-plan-record.v2"
    assert store.record["request"] == semantic.model_dump(mode="json")
    assert store.record["source"]["score_id"] == score
    assert first[0][0].payload.track.clips[0].notes[-1].start_tick < bars * beats * 480
    store.record["request"]["intent"] = "different intent"
    with pytest.raises(ValueError, match="PIANO_PLAN_RECORD_CONTEXT_MISMATCH"):
        await service.PianoSemanticService(None, store, forbidden).prepare(
            req, base, thread_id="v2"
        )


@pytest.mark.asyncio
async def test_v1_cannot_pay_for_new_source_and_wrong_v2_source_rejected_before_factory(
    monkeypatch,
):
    import motif_forge.application.piano_semantic as service

    base, _ = fixture("c01-minuet-g-a16.v1", 3, 16)
    for semantic in [
        PianoSemanticRequest(intent="加伴奏", mode="append"),
        PianoSemanticRequestV2(
            source_score_id="c02-la-candeur-a8.v1",
            beats_per_bar=4,
            mode="append",
            end_bar=8,
            intent="加伴奏",
        ),
    ]:
        run = SimpleNamespace(
            project_id=base.project_id,
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            run_id=uuid4(),
            edit_request={
                "intent": semantic.intent,
                "selection": {},
                "piano_request": semantic.model_dump(mode="json"),
            },
        )

        async def load(_, selected_run=run):
            return selected_run

        monkeypatch.setattr(service, "ReadAIRunByThreadId", lambda _: load)

        def forbidden(_):
            raise AssertionError("must reject before constructing planner")

        with pytest.raises(ValueError, match="PIANO_SOURCE_MISMATCH"):
            await service.PianoSemanticService(None, None, forbidden).prepare(
                PianoPreviewRequest(
                    project_id=run.project_id,
                    branch_id=run.branch_id,
                    base_revision_id=run.base_revision_id,
                    request_id=run.run_id,
                    semantic=semantic,
                ),
                base,
                thread_id="v2",
            )
