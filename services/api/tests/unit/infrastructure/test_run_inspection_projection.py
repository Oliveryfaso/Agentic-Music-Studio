from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from motif_forge.infrastructure.persistence import run_inspection as module
from motif_forge.infrastructure.persistence.tables import (
    AIRunApprovalRow,
    AIRunEditDecisionRow,
    AIRunEventRow,
    AIRunRow,
    AudioArtifactRow,
    ExportBundleArtifactRow,
    MediaJobRow,
)
from sqlalchemy.engine import IteratorResult
from sqlalchemy.engine.result import SimpleResultMetaData
from sqlalchemy.sql import operators


def uid(value: int) -> UUID:
    return UUID(int=value)


NOW = datetime(2026, 10, 25, tzinfo=UTC)


def result(rows: list[object]) -> IteratorResult:
    return IteratorResult(SimpleResultMetaData(["row"]), iter((row,) for row in rows))


def bundle(value: int, plan: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=uid(value), project_id=uid(2), revision_id=uid(3), plan_hash=plan)


def job(value: int, output: int | None, *, job_type: str = "export_bundle") -> SimpleNamespace:
    return SimpleNamespace(
        id=uid(value), project_id=uid(2), input_payload={"revision_id": str(uid(3))},
        result_artifact_id=uid(output) if output is not None else None,
        job_type=job_type, status="succeeded", attempts=1, error_code=None, created_at=NOW,
    )


def event(sequence: int, event_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        sequence=sequence, event_type=event_type, phase="test", created_at=NOW,
        payload={},
    )


class ProjectionSession:
    """Synthetic adapter rows; real SQLAlchemy cardinality and query bounds are retained."""

    def __init__(
        self, bundles: list[object], jobs: list[object], project_jobs: list[object] | None = None,
    ) -> None:
        self.bundles = bundles
        self.jobs = jobs
        self.project_jobs = project_jobs if project_jobs is not None else jobs
        self.queries: list[object] = []
        self.events: list[object] = []
        self.run = SimpleNamespace(
            id=uid(1), project_id=uid(2), thread_id="owned-thread", run_type="generate",
            status="succeeded", version=5, materialized_revision_id=uid(3),
            graph_topology_version="motif-forge-parent.v2", state_schema_version="parent-state.v2",
            submitted_model_requests=0, max_model_requests=3, max_total_tokens=12_000,
        )

    async def __aenter__(self) -> ProjectionSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def execute(self, statement):  # type: ignore[no-untyped-def]
        self.queries.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        if entity is AIRunRow:
            return result([self.run])
        if entity is AIRunEventRow:
            if len(statement.column_descriptions) == 2:
                counts = Counter(row.event_type for row in self.events)
                return IteratorResult(
                    SimpleResultMetaData(["event_type", "event_count"]), iter(counts.items()),
                )
            rows = sorted(self.events, key=lambda row: row.sequence, reverse=True)
            if statement._limit_clause is not None:
                rows = rows[:statement._limit_clause.value]
            return result(rows)
        if entity in (AIRunApprovalRow, AIRunEditDecisionRow, AudioArtifactRow):
            return result([])
        if entity is MediaJobRow:
            return result(self.jobs if statement._setup_joins else self.project_jobs)
        if entity is ExportBundleArtifactRow:
            rows = self.bundles
            for clause in statement._where_criteria:
                if (
                    getattr(clause.left, "name", None) == "id"
                    and clause.operator is operators.in_op
                ):
                    rows = [row for row in rows if row.id in clause.right.value]
            return result(rows)
        raise AssertionError(f"unexpected query entity: {entity}")


@pytest.fixture
def usage(monkeypatch):  # type: ignore[no-untyped-def]
    async def read_usage(_session, _run):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            model_usage_status=SimpleNamespace(value="known"),
            cost=SimpleNamespace(status=SimpleNamespace(value="known"), amount_microusd=0),
        )

    monkeypatch.setattr(module, "read_ai_run_with_pending_usage", read_usage)


@pytest.mark.asyncio
async def test_inspector_binds_bundle_to_own_completed_output_with_two_plans(usage) -> None:
    session = ProjectionSession([bundle(11, "a" * 64), bundle(12, "b" * 64)], [job(21, 12)])

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id == uid(12)


@pytest.mark.asyncio
async def test_inspector_does_not_claim_other_runs_single_bundle_when_it_has_no_output(
    usage,
) -> None:
    session = ProjectionSession([bundle(11, "a" * 64)], [job(21, None)])

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id is None


@pytest.mark.asyncio
async def test_recovery_counts_entire_run_while_timeline_keeps_latest_200(usage) -> None:
    session = ProjectionSession([], [])
    session.events = [event(1, "ai_run.cancelled")] + [
        event(i, "candidate.critic.completed") for i in range(2, 203)
    ]

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None
    assert len(facts.timeline) == 200 and facts.timeline_truncated
    assert all(item.event_type != "ai_run.cancelled" for item in facts.timeline)
    assert facts.recovery.cancel_events == 1


@pytest.mark.asyncio
async def test_recovery_classifies_exact_persisted_event_types_not_substrings(usage) -> None:
    session = ProjectionSession([], [])
    session.events = [event(i, name) for i, name in enumerate([
        "unrecognized.resume_hint", "unrecognized.replay_hint", "unrecognized.retry_hint",
        "unrecognized.cancel_hint", "ai_run.cancelled.audit",
    ], 1)]

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None
    assert facts.recovery.resume_events is None
    assert facts.recovery.replay_events is None
    assert facts.recovery.retry_events is None
    assert facts.recovery.cancel_events == 0


@pytest.mark.asyncio
async def test_distinct_persisted_events_are_counted_as_rows_not_unique_type_names(usage) -> None:
    session = ProjectionSession([], [])
    session.events = [event(1, "ai_run.cancelled"), event(2, "ai_run.cancelled")]

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.recovery.cancel_events == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [11, 12])
async def test_inspector_binds_exact_output_when_legacy_and_new_bundle_coexist(
    usage, output,
) -> None:
    session = ProjectionSession([bundle(11, None), bundle(12, "b" * 64)], [job(21, output)])

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id == uid(output)


@pytest.mark.asyncio
async def test_inspector_keeps_legacy_single_bundle_from_own_output(usage) -> None:
    session = ProjectionSession([bundle(11, None)], [job(21, 11)])

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id == uid(11)


@pytest.mark.asyncio
async def test_inspector_does_not_guess_when_own_run_has_distinct_bundle_outputs(usage) -> None:
    session = ProjectionSession(
        [bundle(11, "a" * 64), bundle(12, "b" * 64)], [job(21, 11), job(22, 12)],
    )

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id is None


@pytest.mark.asyncio
async def test_inspector_deduplicates_shared_output_and_supports_reused_bundle(usage) -> None:
    session = ProjectionSession([bundle(11, "a" * 64)], [job(21, 11), job(22, 11)])

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id == uid(11)


@pytest.mark.asyncio
async def test_inspector_ignores_other_thread_output_even_on_same_revision(usage) -> None:
    session = ProjectionSession([bundle(11, "a" * 64)], [job(21, None)], [job(22, 11)])

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id is None


@pytest.mark.asyncio
async def test_inspector_does_not_bind_non_bundle_or_unfinished_job_result(usage) -> None:
    render = job(21, 11, job_type="render_canonical")
    unfinished = job(22, 11)
    unfinished.status = "cancelled"
    session = ProjectionSession([bundle(11, "a" * 64)], [render, unfinished])

    facts = await module.PostgresRunInspectionStore(lambda: session).read_run_inspection(uid(1))

    assert facts is not None and facts.run.bundle_id is None
