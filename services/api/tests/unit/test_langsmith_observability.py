from __future__ import annotations

from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any
from uuid import UUID

import pytest
from motif_forge.config import Settings
from motif_forge.observability import (
    configure_langsmith,
    graph_trace_config,
    safe_trace,
)


class _TraceContext(AbstractContextManager["_TraceRun"]):
    def __init__(self, *, fail_enter: bool = False, fail_exit: bool = False) -> None:
        self.fail_enter = fail_enter
        self.fail_exit = fail_exit
        self.run = _TraceRun()

    def __enter__(self) -> _TraceRun:
        if self.fail_enter:
            raise RuntimeError("trace setup unavailable")
        return self.run

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self.fail_exit:
            raise RuntimeError("trace finalization unavailable")
        return None


class _TraceRun:
    def __init__(self) -> None:
        self.outputs: dict[str, Any] | None = None

    def add_outputs(self, outputs: dict[str, Any]) -> None:
        self.outputs = outputs


def test_configure_langsmith_requires_key_and_never_exports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_calls: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    client = object()
    monkeypatch.setattr(
        "motif_forge.observability.langsmith.Client",
        lambda **kwargs: client_calls.append(kwargs) or client,
    )
    monkeypatch.setattr(
        "motif_forge.observability.langsmith.configure",
        lambda **kwargs: calls.append(kwargs),
    )
    settings = Settings.for_test(
        langsmith_tracing=True,
        langsmith_api_key="lsv2_pt_do-not-export",
    )

    assert configure_langsmith(settings, service="api") is True

    assert client_calls == [
        {
            "api_url": "https://api.smith.langchain.com",
            "api_key": "lsv2_pt_do-not-export",
            "hide_inputs": True,
            "hide_outputs": True,
        }
    ]
    assert calls == [
        {
            "client": client,
            "enabled": True,
            "project_name": "motif-forge-local",
            "tags": ["motif-forge", "service:api", "environment:test"],
            "metadata": {"service": "api", "environment": "test"},
        }
    ]
    assert "do-not-export" not in repr(calls)


def test_configure_langsmith_disables_tracing_when_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "motif_forge.observability.langsmith.Client",
        lambda **_kwargs: pytest.fail("disabled tracing must not create a client"),
    )
    monkeypatch.setattr(
        "motif_forge.observability.langsmith.configure",
        lambda **kwargs: calls.append(kwargs),
    )

    enabled = configure_langsmith(
        Settings.for_test(langsmith_tracing=True),
        service="resume-dispatcher",
    )

    assert enabled is False
    assert calls == [
        {
            "enabled": False,
            "project_name": "motif-forge-local",
            "tags": [
                "motif-forge",
                "service:resume-dispatcher",
                "environment:test",
            ],
            "metadata": {"service": "resume-dispatcher", "environment": "test"},
        }
    ]


def test_configure_langsmith_is_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[bool] = []
    monkeypatch.setattr(
        "motif_forge.observability.langsmith.Client",
        lambda **_kwargs: object(),
    )

    def failing_configure(**kwargs: Any) -> None:
        attempts.append(bool(kwargs["enabled"]))
        raise RuntimeError("telemetry backend unavailable")

    monkeypatch.setattr(
        "motif_forge.observability.langsmith.configure", failing_configure
    )

    enabled = configure_langsmith(
        Settings.for_test(
            langsmith_tracing=True,
            langsmith_api_key="lsv2_pt_fail-open",
        ),
        service="api",
    )

    assert enabled is False
    assert attempts == [True, False]


def test_graph_trace_config_contains_only_approved_correlation_fields() -> None:
    config = graph_trace_config(
        thread_id="thread-42",
        operation="generate",
        service="resume-dispatcher",
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        project_id=UUID("00000000-0000-0000-0000-000000000002"),
        run_type="generate",
    )

    assert config == {
        "configurable": {"thread_id": "thread-42"},
        "tags": [
            "motif-forge",
            "graph:motif-forge-parent.v2",
            "operation:generate",
            "service:resume-dispatcher",
        ],
        "metadata": {
            "thread_id": "thread-42",
            "operation": "generate",
            "graph_version": "motif-forge-parent.v2",
            "run_id": "00000000-0000-0000-0000-000000000001",
            "project_id": "00000000-0000-0000-0000-000000000002",
            "run_type": "generate",
        },
    }
    serialized = repr(config).lower()
    for forbidden in ("prompt", "reasoning", "authorization", "api_key", "path"):
        assert forbidden not in serialized


@pytest.mark.parametrize("failure_point", ["enter", "exit"])
def test_safe_trace_failures_do_not_change_application_results(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    trace_context = _TraceContext(
        fail_enter=failure_point == "enter",
        fail_exit=failure_point == "exit",
    )
    monkeypatch.setattr(
        "motif_forge.observability.langsmith.trace",
        lambda **_kwargs: trace_context,
    )

    with safe_trace(
        name="DeepSeekV4Flash",
        run_type="llm",
        inputs={"model": "deepseek-v4-flash"},
    ) as trace_run:
        trace_run.add_outputs({"total_tokens": 12})
        result = "application-result"

    assert result == "application-result"
    if failure_point == "exit":
        assert trace_context.run.outputs == {"total_tokens": 12}


def test_safe_trace_preserves_original_application_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "motif_forge.observability.langsmith.trace",
        lambda **_kwargs: _TraceContext(fail_exit=True),
    )

    with pytest.raises(ValueError, match="provider response invalid"), safe_trace(
        name="DeepSeekV4Flash",
        run_type="llm",
        inputs={"model": "deepseek-v4-flash"},
    ):
        raise ValueError("provider response invalid")
