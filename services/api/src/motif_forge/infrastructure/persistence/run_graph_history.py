"""Read-only access to bounded LangGraph task-path evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from motif_forge.application.errors import ApplicationError
from motif_forge.application.run_graph_history import (
    PathKind,
    RunGraphHistory,
    RunGraphTaskPath,
)
from motif_forge.infrastructure.checkpoints import CHECKPOINT_SCHEMA
from motif_forge.infrastructure.persistence.database import SessionFactory

_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_PULL_PREFIX = "~__pregel_pull, "
_PUSH_PREFIX = "~__pregel_push, "
_INCOMPATIBLE_SQLSTATES = frozenset({"3F000", "42P01", "42703"})
MAX_TASK_PATHS = 4096


def validate_checkpoint_schema(schema: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(schema) is None:
        raise ValueError("Checkpoint schema must be a safe PostgreSQL identifier")
    return schema


def parse_task_path(task_path: str, checkpoint_ns: str) -> tuple[str | None, PathKind]:
    if task_path.startswith(_PULL_PREFIX):
        name = task_path.removeprefix(_PULL_PREFIX).strip()
        return (name, "pull") if name else (None, "unknown")
    if task_path.startswith(_PUSH_PREFIX):
        leaf = checkpoint_ns.rsplit("|", maxsplit=1)[-1]
        name, separator, _task_id = leaf.partition(":")
        if separator and name:
            return name, "push"
    return None, "unknown"


def normalize_task_path_rows(
    rows: Iterable[Mapping[str, object]], *, limit: int = MAX_TASK_PATHS
) -> tuple[tuple[RunGraphTaskPath, ...], bool]:
    unique: dict[tuple[str, str, str, str], RunGraphTaskPath] = {}
    for row in rows:
        checkpoint_ns = str(row.get("checkpoint_ns") or "")
        checkpoint_id = str(row.get("checkpoint_id") or "")
        task_id = str(row.get("task_id") or "")
        task_path = str(row.get("task_path") or "")
        key = (checkpoint_id, checkpoint_ns, task_path, task_id)
        technical_name, path_kind = parse_task_path(task_path, checkpoint_ns)
        unique[key] = RunGraphTaskPath(
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
            task_id=task_id,
            task_path=task_path,
            technical_name=technical_name,
            path_kind=path_kind,
        )
    ordered = tuple(unique[key] for key in sorted(unique))
    return ordered[:limit], len(ordered) > limit


def _sqlstate(error: SQLAlchemyError) -> str | None:
    original = getattr(error, "orig", None)
    value = getattr(original, "sqlstate", None)
    return cast(str | None, value)


class PostgresRunGraphHistoryStore:
    def __init__(self, session_factory: SessionFactory, *, schema: str = CHECKPOINT_SCHEMA) -> None:
        self._session_factory = session_factory
        self._schema = validate_checkpoint_schema(schema)

    async def read_run_graph_history(self, thread_id: str) -> RunGraphHistory:
        count_statement = text(
            f"SELECT count(*) FROM {self._schema}.checkpoints WHERE thread_id=:thread_id"
        )
        paths_statement = text(
            "SELECT DISTINCT checkpoint_ns, checkpoint_id, task_id, task_path "
            f"FROM {self._schema}.checkpoint_writes "
            "WHERE thread_id=:thread_id AND task_path <> '' "
            "ORDER BY checkpoint_id, checkpoint_ns, task_path, task_id "
            f"LIMIT {MAX_TASK_PATHS + 1}"
        )
        try:
            async with self._session_factory() as session:
                checkpoint_count = int(
                    (await session.execute(count_statement, {"thread_id": thread_id})).scalar_one()
                )
                rows = (await session.execute(paths_statement, {"thread_id": thread_id})).mappings()
                task_paths, truncated = normalize_task_path_rows(
                    cast(Iterable[Mapping[str, object]], rows)
                )
        except SQLAlchemyError as error:
            if _sqlstate(error) in _INCOMPATIBLE_SQLSTATES:
                return RunGraphHistory(
                    checkpoint_count=0,
                    task_paths=(),
                    truncated=False,
                    schema_compatible=False,
                )
            raise ApplicationError(
                "CHECKPOINT_HISTORY_READ_FAILED",
                "checkpoint execution history could not be read",
                retryable=True,
            ) from error
        return RunGraphHistory(
            checkpoint_count=checkpoint_count,
            task_paths=task_paths,
            truncated=truncated,
            schema_compatible=True,
        )
