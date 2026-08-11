"""Native DeepSeek V4 Flash JSON adapter.

The adapter owns HTTP retries and protocol validation. It never exposes
``reasoning_content`` to graph state, ordinary logs, or its public result.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from motif_forge.agent.planner import PlannerError, PlannerResponse, PlannerUsage
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan

DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
COMPOSITION_PROMPT_VERSION = "composition-planner.v1"

T = TypeVar("T", bound=BaseModel)
ThinkingMode = Literal["enabled", "disabled"]
ReasoningEffort = Literal["high", "max"]


class DeepSeekConfigurationError(PlannerError):
    def __init__(self, code: str, summary: str) -> None:
        super().__init__(
            code,
            summary,
            category="configuration",
            retryable=False,
            suggested_route="human",
        )


class DeepSeekProviderError(PlannerError):
    """Sanitized DeepSeek transport or protocol error."""

    def __init__(
        self,
        code: str,
        summary: str,
        *,
        retryable: bool,
        suggested_route: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            code,
            summary,
            category="model_provider",
            retryable=retryable,
            suggested_route=suggested_route,
        )
        self.status_code = status_code


class _ResponseMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    content: str | None = None


class _ResponseChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    finish_reason: Literal[
        "stop",
        "length",
        "content_filter",
        "tool_calls",
        "insufficient_system_resource",
    ]
    message: _ResponseMessage


class _CompletionTokenDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    reasoning_tokens: int = 0


class _ResponseUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    completion_tokens_details: _CompletionTokenDetails | None = None


class _ChatCompletion(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    choices: tuple[_ResponseChoice, ...] = Field(min_length=1)
    usage: _ResponseUsage = Field(default_factory=_ResponseUsage)


@dataclass(frozen=True, slots=True)
class DeepSeekStructuredResponse[T: BaseModel]:
    output: T
    usage: PlannerUsage
    finish_reason: Literal["stop"] = "stop"
    provider: str = "deepseek"
    model: str = DEEPSEEK_MODEL


def _message_payload(message: BaseMessage) -> dict[str, str]:
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, HumanMessage):
        role = "user"
    else:
        raise DeepSeekConfigurationError(
            "DEEPSEEK_UNSUPPORTED_MESSAGE",
            "The JSON planning adapter accepts only system and user messages.",
        )
    if not isinstance(message.content, str):
        raise DeepSeekConfigurationError(
            "DEEPSEEK_MULTIMODAL_MESSAGE_UNSUPPORTED",
            "The JSON planning adapter accepts text messages only.",
        )
    return {"role": role, "content": message.content}


class DeepSeekJsonClient:
    """Small direct client for DeepSeek's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEEPSEEK_MODEL,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 45.0,
        max_attempts: int = 2,
        backoff_seconds: float = 0.05,
        jitter: Callable[[], float] = random.random,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        secret = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not secret or not secret.strip():
            raise DeepSeekConfigurationError(
                "DEEPSEEK_API_KEY_MISSING",
                "DeepSeek API key is not configured.",
            )
        if model != DEEPSEEK_MODEL:
            raise DeepSeekConfigurationError(
                "DEEPSEEK_MODEL_UNSUPPORTED",
                f"This release requires model {DEEPSEEK_MODEL}.",
            )
        if not base_url.startswith("https://"):
            raise DeepSeekConfigurationError(
                "DEEPSEEK_BASE_URL_INVALID",
                "DeepSeek base URL must use HTTPS.",
            )
        if connect_timeout_seconds <= 0 or read_timeout_seconds <= 0:
            raise DeepSeekConfigurationError(
                "DEEPSEEK_TIMEOUT_INVALID",
                "DeepSeek timeouts must be positive.",
            )
        if not 1 <= max_attempts <= 3:
            raise DeepSeekConfigurationError(
                "DEEPSEEK_ATTEMPTS_INVALID",
                "DeepSeek max_attempts must be between 1 and 3.",
            )

        self._api_key = secret
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_attempts = max_attempts
        self._backoff_seconds = max(0.0, backoff_seconds)
        self._jitter = jitter
        self._sleep = sleep
        self._owns_client = http_client is None
        timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=10.0,
            pool=5.0,
        )
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete_json(
        self,
        *,
        messages: Sequence[BaseMessage],
        output_model: type[T],
        thinking: ThinkingMode,
        reasoning_effort: ReasoningEffort = "high",
        max_tokens: int = 2400,
    ) -> DeepSeekStructuredResponse[T]:
        if not 256 <= max_tokens <= 8192:
            raise DeepSeekConfigurationError(
                "DEEPSEEK_MAX_TOKENS_INVALID",
                "DeepSeek max_tokens must be between 256 and 8192.",
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_message_payload(message) for message in messages],
            "thinking": {"type": thinking},
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
        }
        if thinking == "enabled":
            payload["reasoning_effort"] = reasoning_effort
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                if attempt < self._max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise DeepSeekProviderError(
                    "DEEPSEEK_TIMEOUT",
                    "DeepSeek did not respond within the configured timeout.",
                    retryable=True,
                    suggested_route="retry",
                ) from exc
            except httpx.NetworkError as exc:
                if attempt < self._max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise DeepSeekProviderError(
                    "DEEPSEEK_NETWORK_ERROR",
                    "DeepSeek could not be reached.",
                    retryable=True,
                    suggested_route="retry",
                ) from exc

            if response.status_code >= 400:
                error = self._map_http_error(response.status_code)
                if error.retryable and attempt < self._max_attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise error

            try:
                completion = _ChatCompletion.model_validate_json(response.text, strict=True)
            except (ValueError, ValidationError) as exc:
                raise DeepSeekProviderError(
                    "DEEPSEEK_PROTOCOL_INVALID",
                    "DeepSeek returned an invalid chat completion envelope.",
                    retryable=False,
                    suggested_route="repair",
                ) from exc

            choice = completion.choices[0]
            if (
                choice.finish_reason == "insufficient_system_resource"
                and attempt < self._max_attempts
            ):
                await self._sleep(self._retry_delay(attempt))
                continue
            self._require_stop(choice.finish_reason)
            content = choice.message.content
            if content is None or not content.strip():
                raise DeepSeekProviderError(
                    "DEEPSEEK_EMPTY_CONTENT",
                    "DeepSeek returned no structured result.",
                    retryable=False,
                    suggested_route="repair",
                )
            try:
                parsed = output_model.model_validate_json(content, strict=True)
            except (ValueError, ValidationError) as exc:
                raise DeepSeekProviderError(
                    "DEEPSEEK_SCHEMA_INVALID",
                    "DeepSeek returned JSON that does not match the required schema.",
                    retryable=False,
                    suggested_route="repair",
                ) from exc

            usage = completion.usage
            return DeepSeekStructuredResponse(
                output=parsed,
                usage=PlannerUsage(
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    prompt_cache_hit_tokens=usage.prompt_cache_hit_tokens,
                    prompt_cache_miss_tokens=usage.prompt_cache_miss_tokens,
                    reasoning_tokens=(
                        usage.completion_tokens_details.reasoning_tokens
                        if usage.completion_tokens_details is not None
                        else 0
                    ),
                ),
            )

        raise AssertionError("bounded DeepSeek attempt loop exited unexpectedly")

    def _retry_delay(self, failed_attempt: int) -> float:
        """Return bounded exponential backoff with up to 25% positive jitter."""

        exponential = float(self._backoff_seconds * (2 ** (failed_attempt - 1)))
        jitter_value = min(max(float(self._jitter()), 0.0), 1.0)
        return exponential * (1.0 + jitter_value * 0.25)

    @staticmethod
    def _map_http_error(status_code: int) -> DeepSeekProviderError:
        if status_code in {401, 402, 403}:
            return DeepSeekProviderError(
                f"DEEPSEEK_HTTP_{status_code}",
                "DeepSeek authentication, authorization, or balance requires attention.",
                retryable=False,
                suggested_route="human",
                status_code=status_code,
            )
        retryable = status_code == 429 or status_code in {500, 502, 503, 504}
        return DeepSeekProviderError(
            f"DEEPSEEK_HTTP_{status_code}",
            "DeepSeek request failed.",
            retryable=retryable,
            suggested_route="retry" if retryable else "terminal",
            status_code=status_code,
        )

    @staticmethod
    def _require_stop(finish_reason: str) -> None:
        routes = {
            "length": (
                "DEEPSEEK_OUTPUT_TRUNCATED",
                "DeepSeek output was truncated and has been discarded.",
                "repair",
                False,
            ),
            "content_filter": (
                "DEEPSEEK_CONTENT_FILTERED",
                "DeepSeek did not return a result because of content filtering.",
                "human",
                False,
            ),
            "tool_calls": (
                "DEEPSEEK_UNEXPECTED_TOOL_CALL",
                "DeepSeek requested a tool in a tool-free planning call.",
                "repair",
                False,
            ),
            "insufficient_system_resource": (
                "DEEPSEEK_INSUFFICIENT_RESOURCE",
                "DeepSeek could not complete the request because service resources "
                "were unavailable.",
                "retry",
                True,
            ),
        }
        if finish_reason == "stop":
            return
        code, summary, route, retryable = routes[finish_reason]
        raise DeepSeekProviderError(
            code,
            summary,
            retryable=retryable,
            suggested_route=route,
        )


class DeepSeekCompositionPlanner:
    """CompositionPlanner implementation fixed to thinking/high JSON output."""

    def __init__(
        self,
        client: DeepSeekJsonClient,
        *,
        prompt_text: str,
        prompt_version: str = COMPOSITION_PROMPT_VERSION,
        max_tokens: int = 2400,
    ) -> None:
        if "JSON" not in prompt_text.upper():
            raise DeepSeekConfigurationError(
                "DEEPSEEK_JSON_INSTRUCTION_MISSING",
                "Composition planner prompt must explicitly request JSON.",
            )
        self._client = client
        self._prompt_text = prompt_text
        self._prompt_version = prompt_version
        self._max_tokens = max_tokens

    async def create_plan(self, brief: CompositionBrief) -> PlannerResponse:
        schema = CompositionPlan.model_json_schema()
        messages: tuple[BaseMessage, ...] = (
            SystemMessage(
                content=(
                    f"{self._prompt_text}\n\n"
                    "Return exactly one JSON object matching this JSON Schema:\n"
                    f"{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}"
                )
            ),
            HumanMessage(content=json.dumps(brief.model_dump(mode="json"), ensure_ascii=False)),
        )
        result = await self._client.complete_json(
            messages=messages,
            output_model=CompositionPlan,
            thinking="enabled",
            reasoning_effort="high",
            max_tokens=self._max_tokens,
        )
        return PlannerResponse(
            plan_payload=result.output.model_dump(mode="json"),
            usage=result.usage,
            provider=result.provider,
            model=result.model,
            prompt_version=self._prompt_version,
            schema_version=result.output.schema_version,
        )
