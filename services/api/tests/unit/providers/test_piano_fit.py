"""Offline native Provider boundary, not a paid-model musical-quality score."""

import json
from uuid import uuid4

import httpx
import pytest
from motif_forge.application.classical_import import reviewed_score
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.piano_requests import PianoSemanticRequestV2
from motif_forge.providers.deepseek import DeepSeekJsonClient
from motif_forge.providers.piano import DeepSeekPianoPlanner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "score,beats,bars",
    [
        ("c01-minuet-g-a16.v1", 3, 16),
        ("c02-la-candeur-a8.v1", 4, 8),
        ("j01-bethena-a-first8.v1", 3, 8),
    ],
)
async def test_piano_prompt_has_verified_musical_fit_context_without_rewriting_plan(
    score, beats, bars
):
    project = uuid4()
    _, xml = reviewed_score(score)
    base = score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref="score:" + score
    )
    before = base.model_dump_json()
    calls = []
    raw = {
        "schema_version": "accompaniment-plan.v2",
        "beats_per_bar": beats,
        "summary": "offline contract fixture",
        "bars": [
            {
                "bar": b,
                "chord": "C" if score.startswith("c02") else "G",
                "grid": [0],
                "octave": 2,
                "velocity": 42,
                "gate_steps": 2,
            }
            for b in range(1, bars + 1)
        ],
    }

    async def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "model": "offline-contract",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"supported": True, "reason": "offline", "plan": raw}
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        planner = DeepSeekPianoPlanner(
            DeepSeekJsonClient(api_key="mock-only", http_client=http, max_attempts=1)
        )
        result = await planner.create(
            base,
            PianoSemanticRequestV2(
                source_score_id=score,
                beats_per_bar=beats,
                end_bar=bars,
                intent="低音区克制伴奏,尊重乐句",
                mode="append",
            ),
        )
    assert len(calls) == 1 and result["plan"] == raw and base.model_dump_json() == before
    context = json.loads(calls[0]["messages"][1]["content"])["context"]
    assert "musical_fit" in context  # valid RED on old writer: musical context missing
    fit = context["musical_fit"]
    assert fit["policy"] == "piano-musical-fit-context.v1"
    assert fit["pulse_steps"] == list(range(0, beats * 4, 4))
    assert len(fit["bar_candidates"]) == bars and all(len(x[1]) == 2 for x in fit["bar_candidates"])
    if score.startswith("c02"):
        assert [2, "F"] in fit["source_anchors"]
        assert [8, "G"] in fit["cadences"]
        assert fit["terminal_rest_start_step"] == 12
    if score.startswith("j01"):
        assert [8, "D"] in fit["cadences"]
    assert result["fit_policy"] == fit["policy"]
    assert result["prompt_version"] == "piano-accompaniment-prompt.v5"
    assert sum(len(m["content"].encode()) for m in calls[0]["messages"]) <= 8000
