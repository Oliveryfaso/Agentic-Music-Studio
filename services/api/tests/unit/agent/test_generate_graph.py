from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from motif_forge.agent.critic import DeterministicEvidenceCritic
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.generate import GenerateRequest, initial_generate_state
from motif_forge.agent.parent_graph import (
    PARENT_GRAPH_TOPOLOGY_VERSION,
    PARENT_STATE_SCHEMA_VERSION,
    build_parent_graph,
)
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.candidate_previews import CandidatePreviewCursor
from motif_forge.application.generation import (
    CompleteExportCursor,
    MaterializeApprovedCompositionResult,
    PersistPlanningResultResult,
)
from motif_forge.application.media_jobs import EnqueueMediaJobRequest, EnqueueMediaJobResult
from motif_forge.domain.ai_runs import AIRunApproval, composition_plan_content_hash
from motif_forge.domain.candidates import CandidateLabel
from motif_forge.domain.storage import StoragePressureDecision, StorageRoute

from .sample_data import valid_brief_payload, valid_plan_payload


class _MustNotEnqueue:
    async def __call__(self, request: EnqueueMediaJobRequest) -> EnqueueMediaJobResult:
        del request
        raise AssertionError("legacy media enqueue must not handle generate")


class _CountingPlanner:
    def __init__(self, plan: object, *, repaired_plan: object | None = None) -> None:
        self.delegate = StaticCompositionPlanner(plan, repaired_plan=repaired_plan)
        self.calls = 0

    async def create_plan(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self.calls += 1
        return await self.delegate.create_plan(*args, **kwargs)

    async def repair_plan(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        return await self.delegate.repair_plan(*args, **kwargs)


class _Persist:
    def __init__(self) -> None:
        self.calls = 0
        self.plan_id = uuid4()
        self.style_pack_version: str | None = None

    async def __call__(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.style_pack_version = request.style_pack_version
        plan = CompositionPlan.model_validate_json(
            json.dumps(request.planning_result["plan"]), strict=True
        )
        return PersistPlanningResultResult(
            run_id=request.run_id,
            plan_id=self.plan_id,
            plan_hash=composition_plan_content_hash(plan),
            interrupt_ref="plan-approval-interrupt-v1",
            run_version=1,
        )


class _Approval:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return AIRunApproval(
            approval_id=uuid4(),
            run_id=kwargs["run_id"],
            assertion_hash="a" * 64,
            decision=kwargs["decision"],
            actor_id=kwargs["actor_id"],
            expected_plan_content_hash=kwargs["expected_plan_content_hash"],
            interrupt_ref=kwargs["interrupt_ref"],
            decided_at=datetime.now(UTC),
        )


class _Materialize:
    def __init__(self) -> None:
        self.calls = 0
        self.revision_id = uuid4()

    async def __call__(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return MaterializeApprovedCompositionResult(
            status="approved",
            plan_id=request.plan_id,
            candidate_snapshot_id=uuid4(),
            preview_id=uuid4(),
            revision_id=self.revision_id,
            receipt_id=uuid4(),
        )


class _Export:
    def __init__(self) -> None:
        self.enqueue_calls = 0
        self.collect_calls = 0
        self.run_id = uuid4()
        self.job_ids = [uuid4() for _ in range(7)]
        self.artifact_ids = [uuid4() for _ in range(7)]

    async def enqueue(self, cursor: CompleteExportCursor) -> CompleteExportCursor:
        if cursor.pending_job_id is not None or not cursor.pending_steps:
            return cursor
        job_id = self.job_ids[len(cursor.completed_steps)]
        self.enqueue_calls += 1
        return cursor.model_copy(
            update={
                "media_run_id": self.run_id,
                "pending_job_id": job_id,
                "pending_idempotency_key": f"export-step-{len(cursor.completed_steps)}",
            }
        )

    async def collect(
        self, cursor: CompleteExportCursor, *, completed_job_id: UUID | None = None
    ) -> CompleteExportCursor:
        assert completed_job_id == cursor.pending_job_id
        index = len(cursor.completed_steps)
        self.collect_calls += 1
        update: dict[str, object] = {
            "pending_job_id": None,
            "pending_idempotency_key": None,
            "completed_steps": (*cursor.completed_steps, cursor.pending_steps[0]),
            "completed_job_ids": (*cursor.completed_job_ids, completed_job_id),
        }
        if index < 6:
            update["audio_artifact_ids"] = (
                *cursor.audio_artifact_ids,
                self.artifact_ids[index],
            )
        else:
            update["bundle_artifact_id"] = self.artifact_ids[index]
        return cursor.model_copy(update=update)


class _StorageGate:
    def __init__(self, route: StorageRoute) -> None:
        self.route = route
        self.calls = 0

    async def __call__(self, **kwargs: object) -> StoragePressureDecision:
        self.calls += 1
        return StoragePressureDecision(
            operation_id=str(kwargs["operation_id"]),
            project_id=kwargs["project_id"],
            route=self.route,
            matched_rule_id="STO-001" if self.route is StorageRoute.WAIT_FOR_STORAGE else "STO-050",
            explanation_code=(
                "STORAGE_ROOT_NOT_READY"
                if self.route is StorageRoute.WAIT_FOR_STORAGE
                else "STORAGE_OPERATION_CANCELLED_OR_EXPIRED"
            ),
            error_code=(
                "ARTIFACT_ROOT_UNAVAILABLE"
                if self.route is StorageRoute.WAIT_FOR_STORAGE
                else "STORAGE_QUOTA_EXCEEDED"
            ),
        )


class _S5Candidates:
    def __init__(self) -> None:
        self.calls = 0
        self.ids = {label: uuid4() for label in CandidateLabel}
        self.snapshots = {label: uuid4() for label in CandidateLabel}
        self.hashes = {
            label: ("a" if label is CandidateLabel.A else "b") * 64
            for label in CandidateLabel
        }

    async def create(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return SimpleNamespace(
            candidate_id=self.ids[request.label],
            candidate_snapshot_id=self.snapshots[request.label],
            candidate_content_hash=self.hashes[request.label],
            style_pack_version="style:synth-ambient:v1",
            compiler_version="synth-ambient-compiler.v1",
        )


class _S5Previews:
    def __init__(self) -> None:
        self.enqueue_calls = 0
        self.collect_calls = 0
        self.runs: dict[UUID, UUID] = {}
        self.artifacts: dict[UUID, UUID] = {}

    async def enqueue(self, request):  # type: ignore[no-untyped-def]
        self.enqueue_calls += 1
        job_id = uuid4()
        run_id = uuid4()
        self.runs[job_id] = run_id
        self.artifacts[job_id] = uuid4()
        return CandidatePreviewCursor(
            project_id=request.project_id,
            candidate_snapshot_id=request.candidate_snapshot_id,
            candidate_content_hash=request.expected_candidate_content_hash,
            media_run_id=run_id,
            job_id=job_id,
        )

    async def collect(self, cursor, completed_job_id):  # type: ignore[no-untyped-def]
        self.collect_calls += 1
        assert completed_job_id == cursor.job_id
        return cursor.model_copy(
            update={"preview_artifact_id": self.artifacts[completed_job_id]}
        )


class _S5Selection:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.materialize_calls = 0
        self.preview_ids: dict[UUID, UUID] = {}
        self.revision_id = uuid4()

    async def create_preview(self, request):  # type: ignore[no-untyped-def]
        self.preview_calls += 1
        preview_id = self.preview_ids.setdefault(request.candidate_snapshot_id, uuid4())
        return SimpleNamespace(preview_id=preview_id)

    async def materialize(self, request):  # type: ignore[no-untyped-def]
        self.materialize_calls += 1
        return SimpleNamespace(revision_id=self.revision_id)


def _s5_services():  # type: ignore[no-untyped-def]
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    planner = _CountingPlanner(plan)
    persist = _Persist()
    approval = _Approval()
    legacy_materialize = _Materialize()
    export = _Export()
    candidates = _S5Candidates()
    previews = _S5Previews()
    selection = _S5Selection()
    graph = build_parent_graph(
        _MustNotEnqueue(),
        checkpointer=MemorySaver(),
        generate_planner=planner,
        persist_planning_result=persist,
        record_plan_approval=approval,
        materialize_approved_composition=legacy_materialize,
        enqueue_next_complete_export_job=export.enqueue,
        collect_complete_export_artifact=export.collect,
        create_composition_candidate=candidates.create,
        enqueue_candidate_preview=previews.enqueue,
        collect_candidate_preview=previews.collect,
        evidence_critic=DeterministicEvidenceCritic(),
        create_candidate_selection_preview=selection.create_preview,
        materialize_selected_candidate=selection.materialize,
    )
    return graph, candidates, previews, selection, legacy_materialize, export


def _request(**brief_changes: object) -> GenerateRequest:
    brief = {**valid_brief_payload(), **brief_changes}
    return GenerateRequest(
        run_id=uuid4(),
        project_id=uuid4(),
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        brief=CompositionBrief.model_validate_json(json.dumps(brief), strict=True),
        seed=41,
    )


def _services(  # type: ignore[no-untyped-def]
    *,
    planner: _CountingPlanner | None = None,
    storage_gate: _StorageGate | None = None,
):
    plan = CompositionPlan.model_validate_json(json.dumps(valid_plan_payload()), strict=True)
    planner = planner or _CountingPlanner(plan)
    persist = _Persist()
    approval = _Approval()
    materialize = _Materialize()
    export = _Export()
    graph = build_parent_graph(
        _MustNotEnqueue(),
        checkpointer=MemorySaver(),
        generate_planner=planner,
        persist_planning_result=persist,
        record_plan_approval=approval,
        materialize_approved_composition=materialize,
        enqueue_next_complete_export_job=export.enqueue,
        collect_complete_export_artifact=export.collect,
        storage_pressure_gate=storage_gate,
    )
    return graph, planner, persist, approval, materialize, export


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def _approval_resume(state: dict[str, object], decision: str = "approve") -> dict[str, str]:
    return {
        "decision": decision,
        "actor_id": "test-user",
        "approval_assertion": "I reviewed and authorize this exact plan.",
        "expected_plan_hash": str(state["plan_hash"]),
        "note": "unit test",
    }


def _worker_resume(state: dict[str, object], *, status: str = "succeeded") -> dict[str, object]:
    return {
        "schema_version": "worker-resume.v1",
        "run_id": state["media_run_id"],
        "thread_id": state["thread_id"],
        "run_type": "complete_song_export.v1",
        "resume_event_id": f"event-{state['pending_job_id']}",
        "job_id": state["pending_job_id"],
        "status": status,
        "artifact_id": uuid4() if status == "succeeded" else None,
        "error_code": None if status == "succeeded" else "RENDER_FAILED",
    }


def test_initial_generate_state_is_parent_v2_and_compact() -> None:
    state = initial_generate_state(thread_id="generate-thread-1", request=_request())

    assert state["operation"] == "generate"
    assert state["graph_topology_version"] == PARENT_GRAPH_TOPOLOGY_VERSION
    assert PARENT_GRAPH_TOPOLOGY_VERSION == "motif-forge-parent.v2"
    assert state["state_schema_version"] == PARENT_STATE_SCHEMA_VERSION
    assert PARENT_STATE_SCHEMA_VERSION == "motif-forge-parent-state.v2"
    assert UUID(state["run_id"])
    assert UUID(state["project_id"])
    assert "plan" not in state
    assert "arrangement_ir" not in state


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [None, "motif-forge-parent-state.v1"])
async def test_generate_rejects_missing_or_wrong_parent_state_schema(schema: str | None) -> None:
    graph, planner, persist, _, materialize, export = _services()
    state = initial_generate_state(thread_id="invalid-state-schema", request=_request())
    if schema is None:
        state.pop("state_schema_version")
    else:
        state["state_schema_version"] = schema

    result = await graph.ainvoke(state, _config("invalid-state-schema"))

    assert result["terminal_status"] == "failed"
    assert result["error_code"] == "STATE_SCHEMA_VERSION_UNSUPPORTED"
    assert planner.calls == persist.calls == materialize.calls == export.enqueue_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "expected_phase", "expected_error"),
    [
        (StorageRoute.WAIT_FOR_STORAGE, "storage_wait_required", "ARTIFACT_ROOT_UNAVAILABLE"),
        (StorageRoute.FAIL, "failed", "STORAGE_QUOTA_EXCEEDED"),
    ],
)
async def test_generate_export_storage_gate_blocks_enqueue(
    route: StorageRoute, expected_phase: str, expected_error: str
) -> None:
    storage = _StorageGate(route)
    graph, _, _, _, materialize, export = _services(storage_gate=storage)
    thread_id = f"generate-storage-{route.value}"
    waiting = await graph.ainvoke(
        initial_generate_state(thread_id=thread_id, request=_request()), _config(thread_id)
    )
    result = await graph.ainvoke(Command(resume=_approval_resume(waiting)), _config(thread_id))

    assert result["phase"] == expected_phase
    assert result["error_code"] == expected_error
    assert materialize.calls == storage.calls == 1
    assert export.enqueue_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("brief_change", [{"meter": "3/4"}])
async def test_unsupported_strategy_fails_before_planner(brief_change: dict[str, object]) -> None:
    graph, planner, persist, _, materialize, export = _services()
    request = _request(**brief_change)

    result = await graph.ainvoke(
        initial_generate_state(thread_id="unsupported-generate", request=request),
        _config("unsupported-generate"),
    )

    assert result["terminal_status"] == "failed"
    assert result["error_code"] == "GENERATE_STRATEGY_UNSUPPORTED"
    assert planner.calls == persist.calls == materialize.calls == export.enqueue_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("style", "pack_id"),
    [
        ("synth_ambient", "style:synth-ambient:v1"),
        ("minimal_electronic", "style:minimal-electronic:v1"),
        ("classical_chamber", "style:classical-chamber:v1"),
        ("jazz_harmony_improvisation", "style:jazz-harmony-improvisation:v1"),
    ],
)
async def test_four_styles_reach_approval_with_exact_pack_identity(
    style: str, pack_id: str
) -> None:
    request = _request(style=style)
    planner = _CountingPlanner(build_fallback_plan(request.brief))
    graph, planner, persist, _, materialize, export = _services(planner=planner)

    result = await graph.ainvoke(
        initial_generate_state(thread_id=f"style-{style}", request=request),
        _config(f"style-{style}"),
    )

    assert result["phase"] == "waiting_plan_approval"
    assert persist.style_pack_version == pack_id
    assert planner.calls == persist.calls == 1
    assert materialize.calls == export.enqueue_calls == 0


@pytest.mark.asyncio
async def test_valid_plan_persists_then_interrupts_once_with_hash_and_summary() -> None:
    graph, planner, persist, _, materialize, export = _services()
    thread_id = "generate-plan-interrupt"
    state = await graph.ainvoke(
        initial_generate_state(thread_id=thread_id, request=_request()), _config(thread_id)
    )

    prompt = state["__interrupt__"][0].value
    assert state["phase"] == "waiting_plan_approval"
    assert prompt["kind"] == "plan_approval"
    assert prompt["plan_hash"] == state["plan_hash"]
    assert prompt["summary"] == state["plan_summary"]
    assert planner.calls == persist.calls == 1
    assert materialize.calls == export.enqueue_calls == 0
    assert "plan" not in state


@pytest.mark.asyncio
async def test_reject_and_cancel_end_before_materialization_or_enqueue() -> None:
    for resume in ("reject", "cancel"):
        graph, _, _, approval, materialize, export = _services()
        thread_id = f"generate-{resume}"
        waiting = await graph.ainvoke(
            initial_generate_state(thread_id=thread_id, request=_request()), _config(thread_id)
        )
        payload = (
            _approval_resume(waiting, "reject") if resume == "reject" else {"action": "cancel"}
        )
        result = await graph.ainvoke(Command(resume=payload), _config(thread_id))

        assert result["terminal_status"] == ("rejected" if resume == "reject" else "cancelled")
        assert approval.calls == (1 if resume == "reject" else 0)
        assert materialize.calls == export.enqueue_calls == 0


@pytest.mark.asyncio
async def test_approve_materializes_once_and_waits_for_all_seven_exports() -> None:
    graph, planner, persist, approval, materialize, export = _services()
    thread_id = "generate-complete"
    waiting = await graph.ainvoke(
        initial_generate_state(thread_id=thread_id, request=_request()), _config(thread_id)
    )
    state = await graph.ainvoke(Command(resume=_approval_resume(waiting)), _config(thread_id))

    for _ in range(7):
        assert state["phase"] == "waiting_generate_worker"
        state = await graph.ainvoke(Command(resume=_worker_resume(state)), _config(thread_id))

    assert state["terminal_status"] == "succeeded"
    assert len(state["artifact_refs"]) == 7
    assert planner.calls == persist.calls == approval.calls == materialize.calls == 1
    assert export.enqueue_calls == export.collect_calls == 7


@pytest.mark.asyncio
async def test_worker_failure_is_terminal_and_preserves_partial_artifacts() -> None:
    graph, _, _, _, _, export = _services()
    thread_id = "generate-worker-failure"
    waiting = await graph.ainvoke(
        initial_generate_state(thread_id=thread_id, request=_request()), _config(thread_id)
    )
    state = await graph.ainvoke(Command(resume=_approval_resume(waiting)), _config(thread_id))
    state = await graph.ainvoke(Command(resume=_worker_resume(state)), _config(thread_id))
    failed = await graph.ainvoke(
        Command(resume=_worker_resume(state, status="failed_terminal")), _config(thread_id)
    )

    assert failed["terminal_status"] == "failed"
    assert failed["error_code"] == "RENDER_FAILED"
    assert failed["artifact_refs"] == [str(export.artifact_ids[0])]
    assert export.collect_calls == 1


@pytest.mark.asyncio
async def test_deterministic_fallback_still_reaches_plan_approval() -> None:
    invalid = {"schema_version": "composition-plan.v1"}
    planner = _CountingPlanner(invalid, repaired_plan=invalid)
    graph, _, persist, _, _, _ = _services(planner=planner)
    thread_id = "generate-fallback"

    waiting = await graph.ainvoke(
        initial_generate_state(thread_id=thread_id, request=_request()), _config(thread_id)
    )

    assert waiting["phase"] == "waiting_plan_approval"
    assert waiting["fallback_reason"] == "PLAN_SCHEMA_INVALID_AFTER_REPAIR"
    assert planner.calls == 1
    assert persist.calls == 1


@pytest.mark.asyncio
async def test_s5_waits_for_two_previews_and_explicit_selection_before_revision() -> None:
    graph, candidates, previews, selection, legacy_materialize, export = _s5_services()
    thread_id = "generate-s5-selection"
    waiting_plan = await graph.ainvoke(
        initial_generate_state(thread_id=thread_id, request=_request()),
        _config(thread_id),
    )

    state = await graph.ainvoke(
        Command(resume=_approval_resume(waiting_plan)), _config(thread_id)
    )
    assert state["phase"] == "rendering_candidate_previews"
    assert candidates.calls == 2
    assert selection.materialize_calls == legacy_materialize.calls == 0

    state = await graph.ainvoke(Command(resume=_worker_resume(state)), _config(thread_id))
    assert state["phase"] == "rendering_candidate_previews"
    state = await graph.ainvoke(Command(resume=_worker_resume(state)), _config(thread_id))

    assert state["phase"] == "waiting_candidate_selection"
    assert [item["label"] for item in state["candidate_working"]] == ["a", "b"]
    assert previews.enqueue_calls == previews.collect_calls == 2
    assert selection.preview_calls == 2
    assert selection.materialize_calls == legacy_materialize.calls == 0
    selected = state["candidate_working"][1]

    state = await graph.ainvoke(
        Command(
            resume={
                "decision": "select",
                "actor_id": "test-user",
                "selection_assertion": "I compared both previews and select candidate B.",
                "selected_preview_id": selected["selection_preview_id"],
                "expected_candidate_id": selected["candidate_id"],
                "expected_candidate_content_hash": selected["candidate_content_hash"],
                "note": "B has the preferred evidence profile",
            }
        ),
        _config(thread_id),
    )

    assert state["selected_candidate_id"] == selected["candidate_id"]
    assert state["phase"] == "waiting_generate_worker"
    assert selection.materialize_calls == 1
    assert legacy_materialize.calls == 0
    assert export.enqueue_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resume", "terminal"),
    [
        (
            {
                "decision": "reject",
                "actor_id": "test-user",
                "selection_assertion": "I compared both previews and reject both candidates.",
            },
            "rejected",
        ),
        ({"action": "cancel"}, "cancelled"),
    ],
)
async def test_s5_candidate_reject_and_cancel_never_materialize(
    resume: dict[str, object], terminal: str
) -> None:
    graph, _, _, selection, legacy_materialize, export = _s5_services()
    thread_id = f"generate-s5-{terminal}"
    waiting_plan = await graph.ainvoke(
        initial_generate_state(thread_id=thread_id, request=_request()),
        _config(thread_id),
    )
    state = await graph.ainvoke(
        Command(resume=_approval_resume(waiting_plan)), _config(thread_id)
    )
    state = await graph.ainvoke(Command(resume=_worker_resume(state)), _config(thread_id))
    state = await graph.ainvoke(Command(resume=_worker_resume(state)), _config(thread_id))

    result = await graph.ainvoke(Command(resume=resume), _config(thread_id))

    assert result["terminal_status"] == terminal
    assert selection.materialize_calls == legacy_materialize.calls == 0
    assert export.enqueue_calls == 0
