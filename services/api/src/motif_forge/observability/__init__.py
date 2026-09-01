"""Persistent observability contracts and optional developer tracing adapters."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

import langsmith
from langchain_core.runnables import RunnableConfig

from motif_forge.config import Settings

PARENT_GRAPH_VERSION = "motif-forge-parent.v2"


class _TraceRun(Protocol):
    def add_outputs(self, outputs: dict[str, Any]) -> None: ...


@dataclass(slots=True)
class SafeTraceRun:
    """A fail-open handle that admits only explicitly supplied output metadata."""

    _run: _TraceRun | None = None

    def add_outputs(self, outputs: Mapping[str, Any]) -> None:
        if self._run is None:
            return
        try:
            self._run.add_outputs(dict(outputs))
        except Exception:
            # Developer telemetry must never change an application outcome.
            return


def configure_langsmith(settings: Settings, *, service: str) -> bool:
    """Configure optional LangSmith tracing and return its effective state.

    The SDK client receives the secret directly. Global trace tags and metadata
    deliberately contain only the service/environment correlation boundary.
    """

    enabled = settings.langsmith_configured
    tags = ["motif-forge", f"service:{service}", f"environment:{settings.environment}"]
    metadata = {"service": service, "environment": settings.environment}
    try:
        if enabled:
            assert settings.langsmith_api_key is not None
            client = langsmith.Client(
                api_url=settings.langsmith_endpoint,
                api_key=settings.langsmith_api_key.get_secret_value(),
                hide_inputs=settings.langsmith_hide_inputs,
                hide_outputs=settings.langsmith_hide_outputs,
            )
            langsmith.configure(
                client=client,
                enabled=True,
                project_name=settings.langsmith_project,
                tags=tags,
                metadata=metadata,
            )
        else:
            langsmith.configure(
                enabled=False,
                project_name=settings.langsmith_project,
                tags=tags,
                metadata=metadata,
            )
    except Exception:
        with suppress(Exception):
            langsmith.configure(enabled=False)
        return False
    return enabled


def graph_trace_config(
    *,
    thread_id: str,
    operation: str,
    service: str,
    run_id: UUID | str | None = None,
    project_id: UUID | str | None = None,
    run_type: str | None = None,
    graph_version: str = PARENT_GRAPH_VERSION,
) -> RunnableConfig:
    """Build checkpoint-compatible config with an allowlist of safe trace fields."""

    metadata = {
        "thread_id": thread_id,
        "operation": operation,
        "graph_version": graph_version,
    }
    if run_id is not None:
        metadata["run_id"] = str(run_id)
    if project_id is not None:
        metadata["project_id"] = str(project_id)
    if run_type is not None:
        metadata["run_type"] = run_type
    return {
        "configurable": {"thread_id": thread_id},
        "tags": [
            "motif-forge",
            f"graph:{graph_version}",
            f"operation:{operation}",
            f"service:{service}",
        ],
        "metadata": metadata,
    }


@contextmanager
def safe_trace(
    *,
    name: str,
    run_type: Literal["llm"],
    inputs: Mapping[str, Any],
    tags: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[SafeTraceRun]:
    """Create a manual span while isolating every telemetry-only failure."""

    try:
        trace_context = langsmith.trace(
            name=name,
            run_type=run_type,
            inputs=dict(inputs),
            tags=list(tags) if tags is not None else None,
            metadata=metadata,
        )
        run = trace_context.__enter__()
    except Exception:
        yield SafeTraceRun()
        return

    handle = SafeTraceRun(run)
    try:
        yield handle
    except BaseException as application_error:
        with suppress(Exception):
            trace_context.__exit__(
                type(application_error),
                application_error,
                application_error.__traceback__,
            )
        raise
    else:
        with suppress(Exception):
            trace_context.__exit__(None, None, None)
