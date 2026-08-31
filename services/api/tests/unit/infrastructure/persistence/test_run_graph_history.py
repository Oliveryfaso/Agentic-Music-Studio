from __future__ import annotations

import pytest
from motif_forge.infrastructure.persistence.run_graph_history import (
    normalize_task_path_rows,
    parse_task_path,
    validate_checkpoint_schema,
)


def test_parse_task_path_recognizes_pull_push_and_unknown_paths() -> None:
    assert parse_task_path(
        "~__pregel_pull, ValidateBrief", "PlanInputAdapter:root|planning:child"
    ) == ("ValidateBrief", "pull")
    assert parse_task_path(
        "~__pregel_push, 0000000000", "PlanApproval:root|CreateCandidateBranch:child"
    ) == ("CreateCandidateBranch", "push")
    assert parse_task_path("future path", "broken") == (None, "unknown")
    assert parse_task_path("~__pregel_push, 0000000001", "") == (None, "unknown")


def test_normalize_task_rows_is_deterministic_deduplicated_and_bounded() -> None:
    rows = [
        {
            "checkpoint_ns": "",
            "checkpoint_id": "2",
            "task_id": "task-b",
            "task_path": "~__pregel_pull, Beta",
        },
        {
            "checkpoint_ns": "",
            "checkpoint_id": "1",
            "task_id": "task-a",
            "task_path": "~__pregel_pull, Alpha",
        },
        {
            "checkpoint_ns": "",
            "checkpoint_id": "1",
            "task_id": "task-a",
            "task_path": "~__pregel_pull, Alpha",
        },
    ]

    normalized, truncated = normalize_task_path_rows(rows, limit=2)

    assert [item.technical_name for item in normalized] == ["Alpha", "Beta"]
    assert truncated is False

    oversized = [
        {
            "checkpoint_ns": "",
            "checkpoint_id": f"{index:05}",
            "task_id": f"task-{index}",
            "task_path": "~__pregel_pull, WaitForGenerateJobEvent",
        }
        for index in range(4)
    ]
    normalized, truncated = normalize_task_path_rows(oversized, limit=3)
    assert len(normalized) == 3
    assert truncated is True


def test_checkpoint_schema_must_be_a_safe_identifier() -> None:
    assert validate_checkpoint_schema("motif_forge_graph") == "motif_forge_graph"
    with pytest.raises(ValueError, match="safe PostgreSQL identifier"):
        validate_checkpoint_schema("motif_forge_graph; DROP SCHEMA public")
