import json

import httpx
import pytest
from agent.sample_data import valid_brief_payload, valid_plan_payload
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan, StrictSchema
from motif_forge.providers.deepseek import (
    DeepSeekCompositionPlanner,
    DeepSeekConfigurationError,
    DeepSeekJsonClient,
    DeepSeekProviderError,
    DeepSeekToolSpec,
)


class SearchArgs(StrictSchema):
    query: str


def test_missing_api_key_is_a_safe_configuration_error() -> None:
    with pytest.raises(DeepSeekConfigurationError) as exc_info:
        DeepSeekJsonClient(api_key=None)

    assert exc_info.value.code == "DEEPSEEK_API_KEY_MISSING"
    assert exc_info.value.suggested_route == "human"


@pytest.mark.asyncio
async def test_json_planner_uses_explicit_thinking_and_hides_reasoning() -> None:
    captured_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "private chain of thought",
                            "content": json.dumps(valid_plan_payload()),
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 101,
                    "completion_tokens": 80,
                    "total_tokens": 181,
                    "prompt_cache_hit_tokens": 50,
                    "prompt_cache_miss_tokens": 51,
                    "completion_tokens_details": {"reasoning_tokens": 25},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekJsonClient(
            api_key="test-key",
            http_client=http_client,
            max_attempts=1,
        )
        planner = DeepSeekCompositionPlanner(
            client,
            prompt_text="Return JSON only for a safe instrumental macro plan.",
        )
        brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)

        result = await planner.create_plan(brief)

    assert captured_request["model"] == "deepseek-v4-flash"
    assert captured_request["thinking"] == {"type": "enabled"}
    assert captured_request["reasoning_effort"] == "high"
    assert captured_request["response_format"] == {"type": "json_object"}
    assert result.usage.reasoning_tokens == 25
    assert not hasattr(result, "reasoning_content")
    assert "private chain of thought" not in repr(result)
    CompositionPlan.model_validate_json(json.dumps(result.plan_payload), strict=True)


@pytest.mark.asyncio
async def test_length_finish_reason_discards_partial_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"schema_version":'},
                    }
                ],
                "usage": {},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekJsonClient(api_key="test-key", http_client=http_client, max_attempts=1)
        with pytest.raises(DeepSeekProviderError) as exc_info:
            await client.complete_json(
                messages=[],
                output_model=CompositionPlan,
                thinking="enabled",
                max_tokens=512,
            )

    assert exc_info.value.code == "DEEPSEEK_OUTPUT_TRUNCATED"
    assert exc_info.value.suggested_route == "repair"


@pytest.mark.asyncio
async def test_retryable_failures_use_bounded_exponential_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        del request
        attempts += 1
        return httpx.Response(429)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekJsonClient(
            api_key="test-key",
            http_client=http_client,
            max_attempts=3,
            backoff_seconds=0.5,
            jitter=lambda: 0.0,
            sleep=record_sleep,
        )
        with pytest.raises(DeepSeekProviderError) as exc_info:
            await client.complete_json(
                messages=[],
                output_model=CompositionPlan,
                thinking="enabled",
                max_tokens=512,
            )

    assert attempts == 3
    assert delays == [0.5, 1.0]
    assert exc_info.value.code == "DEEPSEEK_HTTP_429"


@pytest.mark.asyncio
async def test_planner_repairs_schema_once_and_aggregates_usage() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = (
            json.dumps({"schema_version": "composition-plan.v1"})
            if len(requests) == 1
            else json.dumps(valid_plan_payload())
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        planner = DeepSeekCompositionPlanner(
            DeepSeekJsonClient(api_key="test-key", http_client=http_client, max_attempts=1),
            prompt_text="Return JSON only for a safe instrumental macro plan.",
        )
        brief = CompositionBrief.model_validate_json(json.dumps(valid_brief_payload()), strict=True)

        result = await planner.create_plan(brief)

    assert len(requests) == 2
    assert result.model_calls == 2
    assert result.usage.total_tokens == 20
    repair_message = requests[1]["messages"][-1]["content"]  # type: ignore[index]
    assert "Safe issue codes" in repair_message
    assert "private chain of thought" not in repair_message
    CompositionPlan.model_validate_json(json.dumps(result.plan_payload), strict=True)


@pytest.mark.asyncio
async def test_thinking_tool_loop_replays_reasoning_content_without_exposing_it() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "tool-turn-1",
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": None,
                                "reasoning_content": "private tool reasoning",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "search_style_knowledge",
                                            "arguments": json.dumps({"query": "ambient"}),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"total_tokens": 10},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "final-turn-2",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(valid_plan_payload())},
                    }
                ],
                "usage": {"total_tokens": 20},
            },
        )

    def search(arguments: StrictSchema) -> dict[str, object]:
        assert isinstance(arguments, SearchArgs)
        return {"matches": [{"style": "synth_ambient"}]}

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekJsonClient(api_key="test-key", http_client=http_client, max_attempts=1)
        result = await client.complete_tool_loop(
            messages=[],
            tools=[
                DeepSeekToolSpec(
                    name="search_style_knowledge",
                    description="Search approved style cards.",
                    arguments_model=SearchArgs,
                    handler=search,
                )
            ],
            output_model=CompositionPlan,
        )

    second_messages = requests[1]["messages"]  # type: ignore[assignment]
    assert second_messages[0]["role"] == "assistant"  # type: ignore[index]
    assert second_messages[0]["reasoning_content"] == "private tool reasoning"  # type: ignore[index]
    assert second_messages[1] == {  # type: ignore[index]
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"matches":[{"style":"synth_ambient"}]}',
    }
    assert result.model_calls == 2
    assert result.usage.total_tokens == 30
    assert "private tool reasoning" not in repr(result)
    assert result.operation_id.startswith("deepseek-tool-loop:")


@pytest.mark.asyncio
async def test_thinking_tool_loop_rejects_missing_reasoning_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_style_knowledge",
                                        "arguments": '{"query":"ambient"}',
                                    },
                                }
                            ]
                        },
                    }
                ],
                "usage": {},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekJsonClient(api_key="test-key", http_client=http_client, max_attempts=1)
        with pytest.raises(DeepSeekProviderError) as exc_info:
            await client.complete_tool_loop(
                messages=[],
                tools=[
                    DeepSeekToolSpec(
                        name="search_style_knowledge",
                        description="Search approved style cards.",
                        arguments_model=SearchArgs,
                        handler=lambda _: {},
                    )
                ],
                output_model=CompositionPlan,
            )

    assert exc_info.value.code == "DEEPSEEK_REASONING_CONTENT_MISSING"
