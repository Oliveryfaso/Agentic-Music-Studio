"""Bounded, payload-free LangGraph execution evidence."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

type PathKind = Literal["pull", "push", "unknown"]


class RunGraphHistoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunGraphTaskPath(RunGraphHistoryModel):
    checkpoint_ns: str
    checkpoint_id: str
    task_id: str
    task_path: str
    technical_name: str | None
    path_kind: PathKind


class RunGraphHistory(RunGraphHistoryModel):
    checkpoint_count: int = Field(ge=0)
    task_paths: tuple[RunGraphTaskPath, ...]
    truncated: bool = False
    schema_compatible: bool = True


class RunGraphHistoryStore(Protocol):
    async def read_run_graph_history(self, thread_id: str) -> RunGraphHistory: ...
