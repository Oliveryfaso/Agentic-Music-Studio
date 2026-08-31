from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.run_graph import ReadRunGraph
from motif_forge.application.run_graph_history import RunGraphHistory, RunGraphTaskPath
from motif_forge.application.run_inspection import (
    DecisionSummary,
    InspectionEvent,
    InspectionJob,
    InspectionRunSummary,
    RecoverySummary,
    RunInspectionFacts,
    RunUsageSummary,
    RunVersionSummary,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


class FakeInspectionStore:
    facts: RunInspectionFacts | None = None

    async def read_run_inspection(self, run_id: UUID) -> RunInspectionFacts | None:
        return self.facts if self.facts and self.facts.run_id == run_id else None


class FakeHistoryStore:
    history = RunGraphHistory(
        checkpoint_count=0, task_paths=(), truncated=False, schema_compatible=True
    )
    requested_thread_id: str | None = None

    async def read_run_graph_history(self, thread_id: str) -> RunGraphHistory:
        self.requested_thread_id = thread_id
        return self.history


def inspection(
    *,
    run_type: str = "generate",
    status: str = "planning",
    phase: str = "planning",
    decisions: tuple[DecisionSummary, ...] = (),
    jobs: tuple[InspectionJob, ...] = (),
) -> RunInspectionFacts:
    return RunInspectionFacts(
        run=InspectionRunSummary(
            run_id=uid(1),
            project_id=uid(2),
            thread_id="thread-generate-1",
            run_type=run_type,
            status=status,
            version=5,
            revision_id=uid(3) if status == "succeeded" else None,
            bundle_id=uid(4) if status == "succeeded" else None,
            error_code="EXPORT_INCOMPLETE" if status == "failed" else None,
        ),
        versions=RunVersionSummary(
            graph_topology_version="motif-forge-parent.v2",
            state_schema_version="parent-state.v2",
        ),
        usage=RunUsageSummary(
            submitted_model_requests=0,
            max_model_requests=3,
            max_total_tokens=12_000,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            usage_status="known",
            cost_status="known",
            cost_amount_microusd=0,
        ),
        timeline=(
            InspectionEvent(
                sequence=1,
                event_type="ai_run.updated",
                phase=phase,
                created_at=datetime(2026, 8, 31, 12, tzinfo=UTC),
                summary={"phase": phase},
            ),
        ),
        timeline_truncated=False,
        decisions=decisions,
        jobs=jobs,
        artifacts=(),
        recovery=RecoverySummary(
            resume_events=0,
            replay_events=0,
            retry_events=0,
            cancel_events=0,
            terminal_outcome=status if status in {"succeeded", "failed"} else None,
        ),
    )


def task(name: str, order: int, *, kind: str = "pull", namespace: str = "") -> RunGraphTaskPath:
    path = f"~__pregel_pull, {name}" if kind == "pull" else f"~__pregel_push, {order:010}"
    return RunGraphTaskPath(
        checkpoint_ns=namespace,
        checkpoint_id=f"{order:04}",
        task_id=f"task-{order}",
        task_path=path,
        technical_name=name,
        path_kind=kind,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_projection_maps_parallel_loops_human_wait_and_safe_counts() -> None:
    inspections = FakeInspectionStore()
    inspections.facts = inspection(
        status="waiting_worker",
        phase="waiting_candidate_selection",
        decisions=(
            DecisionSummary(
                kind="plan",
                decision="approve",
                actor_id="local-user",
                decided_at=datetime(2026, 8, 31, 11, tzinfo=UTC),
            ),
        ),
        jobs=(
            InspectionJob(
                job_id=uid(10),
                job_type="candidate_preview",
                status="succeeded",
                attempts=1,
                error_code=None,
            ),
        ),
    )
    histories = FakeHistoryStore()
    histories.history = RunGraphHistory(
        checkpoint_count=18,
        task_paths=(
            task("ValidateRequest", 1),
            task("ValidateBrief", 2),
            task("CompositionPlanner", 3),
            task("PlanApproval", 4),
            task(
                "CreateCandidateBranch",
                5,
                kind="push",
                namespace="PlanApproval:root|CreateCandidateBranch:a",
            ),
            task(
                "CreateCandidateBranch",
                6,
                kind="push",
                namespace="PlanApproval:root|CreateCandidateBranch:b",
            ),
            task("CandidateFanIn", 7),
            task("EnqueueCandidatePreview", 8),
            task("WaitForCandidatePreview", 9),
            task("EnqueueCandidatePreview", 10),
            task("WaitForCandidatePreview", 11),
            task("CriticizeCandidates", 12),
            task("ApplyCriticRepair", 13),
            task("CreateCandidateSelectionPreviews", 14),
        ),
        truncated=False,
        schema_compatible=True,
    )

    result = await ReadRunGraph(inspections, histories)(uid(1))

    assert histories.requested_thread_id == "thread-generate-1"
    assert result.schema_version == "run-graph-view.v1"
    assert result.evidence_status == "available"
    assert result.current_phase_id == "commit"
    by_id = {node.id: node for node in result.nodes}
    assert by_id["candidates:candidate-a"].evidence == "grouped_parallel"
    assert by_id["candidates:candidate-b"].evidence == "grouped_parallel"
    assert by_id["candidates:enqueue-preview"].iteration_count == 2
    assert by_id["candidates:wait-preview"].iteration_count == 2
    assert by_id["commit:selection"].status == "waiting"
    assert by_id["planning:validate-brief"].occurred_at is None
    assert result.evidence_summary.checkpoint_count == 18
    assert result.evidence_summary.event_count == 1
    assert result.evidence_summary.human_decision_count == 1
    assert result.evidence_summary.job_count == 1
    assert any(edge.relation == "parallel" and edge.status == "traversed" for edge in result.edges)


@pytest.mark.asyncio
async def test_projection_is_honest_for_unavailable_partial_unknown_and_terminal_routes() -> None:
    inspections = FakeInspectionStore()
    inspections.facts = inspection(status="succeeded", phase="succeeded")
    histories = FakeHistoryStore()
    histories.history = RunGraphHistory(
        checkpoint_count=4,
        task_paths=(
            task("ValidateRequest", 1),
            task("MaterializeSelectedCandidate", 2),
            task("FutureNode", 3),
            task("CompleteGenerate", 4),
        ),
        truncated=True,
        schema_compatible=True,
    )

    result = await ReadRunGraph(inspections, histories)(uid(1))

    assert result.evidence_status == "partial"
    by_id = {node.id: node for node in result.nodes}
    assert by_id["commit:materialize-selected"].status == "completed"
    assert by_id["commit:materialize-legacy"].status == "skipped"
    assert result.evidence_summary.unmapped_task_count == 1
    serialized = result.model_dump_json()
    for forbidden in ("prompt", "payload", "approval_assertion", "storage_key", "/private/"):
        assert forbidden not in serialized

    histories.history = RunGraphHistory(
        checkpoint_count=0, task_paths=(), truncated=False, schema_compatible=True
    )
    unavailable = await ReadRunGraph(inspections, histories)(uid(1))
    assert unavailable.evidence_status == "unavailable"
    assert all(node.evidence == "none" for node in unavailable.nodes)


@pytest.mark.asyncio
async def test_projection_rejects_missing_and_non_generate_runs_before_history_read() -> None:
    inspections = FakeInspectionStore()
    histories = FakeHistoryStore()
    use_case = ReadRunGraph(inspections, histories)

    with pytest.raises(ApplicationError, match="AI_RUN_NOT_FOUND"):
        await use_case(uid(99))
    assert histories.requested_thread_id is None

    inspections.facts = inspection(run_type="edit")
    with pytest.raises(ApplicationError) as captured:
        await use_case(uid(1))
    assert captured.value.code == "RUN_GRAPH_UNSUPPORTED"
    assert histories.requested_thread_id is None
