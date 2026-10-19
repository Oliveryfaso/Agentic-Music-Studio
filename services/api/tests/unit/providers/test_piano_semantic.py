import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from motif_forge.agent.planner import PlannerError
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.piano_requests import PianoSemanticRequest
from motif_forge.providers.deepseek import DeepSeekJsonClient


@pytest.mark.asyncio
async def test_piano_prompt_has_musical_context_and_one_bounded_non_thinking_call():
    import motif_forge.resources.scores as scores
    from motif_forge.providers.piano import DeepSeekPianoPlanner

    project = uuid4()
    xml = Path(next(iter(scores.__path__))) / "ode-melody.musicxml"
    base = score_to_arrangement(
        parse_musicxml(xml.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    calls = []

    async def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        assert body["max_tokens"] == 3072 and body["thinking"] == {"type": "disabled"}
        assert "tools" not in body and body["response_format"] == {"type": "json_object"}
        assert (
            "melody" in body["messages"][1]["content"]
            and "api_key" not in body["messages"][1]["content"]
        )
        plan = {
            "schema_version": "accompaniment-plan.v1",
            "summary": "前半稀疏,后半活跃",
            "bars": [
                {
                    "bar": i,
                    "chord": "G",
                    "grid": [0] if i <= 8 else [0, 4, 8, 12],
                    "octave": 2,
                    "velocity": 45,
                    "gate_steps": 3,
                }
                for i in range(1, 17)
            ],
        }
        return httpx.Response(
            200,
            json={
                "id": "fake-one",
                "model": "deepseek-v4.1-flash-1017",
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

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        planner = DeepSeekPianoPlanner(
            DeepSeekJsonClient(api_key="test-only", http_client=http, max_attempts=1)
        )
        result = await planner.create(
            base, PianoSemanticRequest(intent="前半稀疏后半活跃", mode="append")
        )
    assert len(calls) == 1 and result["usage"]["total_tokens"] == 300
    assert result["model"] == "deepseek-v4.1-flash-1017"
    assert len(result["plan"]["bars"][8]["grid"]) > len(result["plan"]["bars"][0]["grid"])


@pytest.mark.asyncio
async def test_out_of_scope_refusal_is_not_silently_rule_generated():
    import motif_forge.resources.scores as scores
    from motif_forge.providers.piano import DeepSeekPianoPlanner

    project = uuid4()
    xml = Path(next(iter(scores.__path__))) / "ode-melody.musicxml"
    base = score_to_arrangement(
        parse_musicxml(xml.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    calls = []

    async def handler(req):
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"supported": False, "reason": "仅支持一条钢琴伴奏", "plan": None}
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        planner = DeepSeekPianoPlanner(
            DeepSeekJsonClient(api_key="test-only", http_client=http, max_attempts=1)
        )
        with pytest.raises(PlannerError, match="intent exceeds"):
            await planner.create(base, PianoSemanticRequest(intent="加第三条小提琴", mode="append"))
    assert len(calls) == 1
