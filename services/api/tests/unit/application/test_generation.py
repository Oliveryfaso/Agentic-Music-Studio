from __future__ import annotations

from datetime import UTC, datetime
from inspect import Parameter, signature
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.errors import ApplicationError
from motif_forge.application.generation import (
    LoadCompositionPlan,
    MaterializeApprovedComposition,
    MaterializeApprovedCompositionRequest,
    PersistPlanningResult,
    PersistPlanningResultRequest,
)
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V1,
    AIRun,
    AIRunApproval,
    AIRunStatus,
    PersistedCompositionPlan,
    composition_plan_content_hash,
)

NOW = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)


def _brief() -> CompositionBrief:
    return CompositionBrief(
        title="Polar Current",
        purpose="Instrumental underscore for a quiet orbital observatory",
        style="synth_ambient",
        duration_seconds=120,
        meter="4/4",
        target_bpm=72,
        target_key="D dorian",
        moods=("weightless", "curious"),
        negative_constraints=("no abrupt drop",),
    )


def _plan(*, energy: float = 0.68) -> CompositionPlan:
    sections = (
        {
            "section_id": "opening",
            "name": "Opening",
            "start_bar": 0,
            "end_bar": 8,
            "function": "Establish the harmonic field",
            "energy": 0.2,
        },
        {
            "section_id": "development",
            "name": "Development",
            "start_bar": 8,
            "end_bar": 28,
            "function": "Develop the pulse and motif",
            "energy": energy,
        },
        {
            "section_id": "resolution",
            "name": "Resolution",
            "start_bar": 28,
            "end_bar": 36,
            "function": "Reduce density and resolve",
            "energy": 0.25,
        },
    )
    return CompositionPlan.model_validate(
        {
            "genre": "synth_ambient",
            "purpose": _brief().purpose,
            "moods": _brief().moods,
            "duration_bars": 36,
            "bpm": 72,
            "meter": "4/4",
            "key": {"tonic": "D", "mode": "dorian"},
            "sections": sections,
            "instrumentation": tuple(
                {
                    "instrument_id": f"layer_{role}",
                    "name": role.title(),
                    "role": role,
                    "pitch_range": "supported built-in range",
                    "entry_section_id": "opening",
                    "exit_section_id": "resolution",
                }
                for role in ("pad", "melody", "bass", "rhythm")
            ),
            "harmonic_language": "Open modal harmony",
            "rhythmic_language": "Sparse pulses",
            "texture": "Layered synthesis",
            "negative_constraints": ("no abrupt drop",),
            "confidence": 0.9,
        },
        strict=True,
    )


class FakeAIRunTransaction:
    def __init__(self, run: AIRun) -> None:
        self.run = run
        self.plans: dict[UUID, PersistedCompositionPlan] = {}
        self.approval: AIRunApproval | None = None
        self.pending_calls = 0

    def __call__(self) -> FakeAIRunTransaction:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    async def read_ai_run(self, run_id: UUID) -> AIRun:
        if run_id != self.run.run_id:
            raise ApplicationError("AI_RUN_NOT_FOUND", "missing")
        return self.run

    async def read_ai_run_projection(self, run_id: UUID):  # type: ignore[no-untyped-def]
        from motif_forge.application.ports import AIRunProjection

        return AIRunProjection(run=await self.read_ai_run(run_id))

    async def persist_composition_plan(
        self, plan: PersistedCompositionPlan
    ) -> PersistedCompositionPlan:
        for existing in self.plans.values():
            if existing.run_id == plan.run_id and existing.content_hash == plan.content_hash:
                return existing
        self.plans[plan.plan_id] = plan
        return plan

    async def read_composition_plan(
        self, *, plan_id: UUID, run_id: UUID
    ) -> PersistedCompositionPlan:
        plan = self.plans.get(plan_id)
        if plan is None or plan.run_id != run_id:
            raise ApplicationError("PLAN_NOT_FOUND", "missing")
        if plan.content_hash != composition_plan_content_hash(
            plan.plan, hash_version=plan.hash_version
        ):
            raise ApplicationError("PLAN_HASH_MISMATCH", "tampered")
        return plan

    async def persist_plan_and_mark_pending(
        self,
        *,
        plan: PersistedCompositionPlan,
        expected_version: int,
        now: datetime,
    ) -> tuple[PersistedCompositionPlan, AIRun]:
        persisted = await self.persist_composition_plan(plan)
        run = await self.mark_ai_run_plan_pending(
            run_id=plan.run_id,
            plan_id=persisted.plan_id,
            expected_version=expected_version,
            now=now,
        )
        return persisted, run

    async def mark_ai_run_plan_pending(
        self, *, run_id: UUID, plan_id: UUID, expected_version: int, now: datetime
    ) -> AIRun:
        self.pending_calls += 1
        plan = await self.read_composition_plan(plan_id=plan_id, run_id=run_id)
        if (
            self.run.status is AIRunStatus.WAITING_APPROVAL
            and self.run.pending_plan_id == plan_id
            and self.run.pending_plan_content_hash == plan.content_hash
        ):
            return self.run
        if self.run.version != expected_version:
            raise ApplicationError("AI_RUN_VERSION_CONFLICT", "stale")
        self.run = self.run.model_copy(
            update={
                "status": AIRunStatus.WAITING_APPROVAL,
                "version": self.run.version + 1,
                "updated_at": now,
                "pending_plan_id": plan_id,
                "pending_plan_content_hash": plan.content_hash,
                "pending_interrupt_ref": "server-generated-interrupt-reference",
            }
        )
        return self.run

    async def read_ai_run_approval(self, run_id: UUID) -> AIRunApproval | None:
        return self.approval if self.approval is not None and run_id == self.run.run_id else None

    async def record_ai_run_approval(
        self,
        *,
        approval: AIRunApproval,
        assertion: str,
        note: str,
        expected_version: int,
        outbox_event_id: UUID,
    ) -> AIRunApproval:
        del assertion, note, outbox_event_id
        if self.approval is not None:
            return self.approval
        if (
            self.run.version != expected_version
            or self.run.status is not AIRunStatus.WAITING_APPROVAL
            or self.run.pending_plan_content_hash != approval.expected_plan_content_hash
            or self.run.pending_interrupt_ref != approval.interrupt_ref
        ):
            raise ApplicationError("AI_RUN_APPROVAL_CONFLICT", "invalid pending approval")
        self.approval = approval
        target = (
            AIRunStatus.MATERIALIZING if approval.decision == "approve" else AIRunStatus.REJECTED
        )
        self.run = self.run.transition(target, now=approval.decided_at).model_copy(
            update={"approval_assertion_hash": approval.assertion_hash}
        )
        return approval

    async def record_idempotent_ai_run_approval(self, **kwargs):  # type: ignore[no-untyped-def]
        return await self.record_ai_run_approval(
            approval=kwargs["approval"], assertion=kwargs["assertion"], note=kwargs["note"],
            expected_version=kwargs["expected_version"],
            outbox_event_id=kwargs["outbox_event_id"],
        )


def _run(project_id: UUID, branch_id: UUID, revision_id: UUID) -> AIRun:
    return AIRun(
        run_id=uuid4(),
        project_id=project_id,
        branch_id=branch_id,
        base_revision_id=revision_id,
        thread_id=f"generate-{uuid4().hex}",
        brief=_brief().model_dump(mode="json"),
        status=AIRunStatus.PLANNING,
        created_at=NOW,
        updated_at=NOW,
    )


def _planning_result(plan: CompositionPlan | None = None) -> dict[str, object]:
    return {
        "phase": "planning_complete",
        "plan": (plan or _plan()).model_dump(mode="json"),
        "provider_metadata": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "prompt_version": "composition-planner.v1",
            "schema_version": "composition-plan.v1",
        },
        "counters": {"model_calls": 1, "total_tokens": 900},
    }


@pytest.mark.asyncio
async def test_persist_planning_result_validates_hashes_and_marks_pending_idempotently() -> None:
    ids = iter((UUID(int=101), UUID(int=102)))
    run = _run(UUID(int=1), UUID(int=2), UUID(int=3))
    ai = FakeAIRunTransaction(run)
    persist = PersistPlanningResult(ai, id_factory=lambda: next(ids), clock=lambda: NOW)
    request = PersistPlanningResultRequest(
        run_id=run.run_id,
        expected_run_version=0,
        planning_result=_planning_result(),
    )

    first = await persist(request)
    replay = await persist(request)

    assert replay.plan_id == first.plan_id
    assert replay.plan_hash == first.plan_hash
    assert replay.interrupt_ref == first.interrupt_ref
    assert replay.run_version == first.run_version == 1
    assert len(ai.plans) == 1


@pytest.mark.asyncio
async def test_load_rejects_tampered_persisted_plan_before_compiler() -> None:
    run = _run(UUID(int=1), UUID(int=2), UUID(int=3))
    ai = FakeAIRunTransaction(run)
    plan = _plan()
    persisted = PersistedCompositionPlan(
        plan_id=uuid4(),
        run_id=run.run_id,
        plan=plan,
        content_hash=composition_plan_content_hash(plan),
        provider="deepseek",
        model="deepseek-v4-flash",
        prompt_version="composition-planner.v1",
        schema_version=plan.schema_version,
        style_pack_version="synth-ambient.v1",
    )
    ai.plans[persisted.plan_id] = persisted.model_copy(update={"content_hash": "0" * 64})

    with pytest.raises(ApplicationError, match="PLAN_HASH_MISMATCH"):
        await LoadCompositionPlan(ai)(
            run_id=run.run_id,
            plan_id=persisted.plan_id,
            expected_plan_hash=persisted.content_hash,
        )


@pytest.mark.asyncio
async def test_v1_collision_unsafe_plan_is_rejected_before_compilation() -> None:
    run = _run(UUID(int=1), UUID(int=2), UUID(int=3))
    ai = FakeAIRunTransaction(run)
    plan = _plan(energy=0.2500001)
    persisted = PersistedCompositionPlan(
        plan_id=uuid4(),
        run_id=run.run_id,
        plan=plan,
        content_hash=composition_plan_content_hash(plan, hash_version=PLAN_HASH_VERSION_V1),
        hash_version=PLAN_HASH_VERSION_V1,
        provider="legacy",
        model="legacy",
        prompt_version="legacy",
        schema_version=plan.schema_version,
        style_pack_version="synth-ambient.v1",
    )
    ai.plans[persisted.plan_id] = persisted

    with pytest.raises(ApplicationError, match="PLAN_HASH_VERSION_UNSAFE"):
        await LoadCompositionPlan(ai)(
            run_id=run.run_id,
            plan_id=persisted.plan_id,
            expected_plan_hash=persisted.content_hash,
            require_compilation_safe=True,
        )


def test_materialization_request_enforces_approval_fields() -> None:
    with pytest.raises(ValueError):
        MaterializeApprovedCompositionRequest(
            run_id=uuid4(),
            project_id=uuid4(),
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            plan_id=uuid4(),
            expected_plan_hash="not-a-hash",
            seed=1,
            actor_id="",
            approval_assertion="too short",
            idempotency_key="materialize-key",
        )


def test_materialization_constructor_requires_the_atomic_uow() -> None:
    parameters = signature(MaterializeApprovedComposition).parameters

    assert parameters["materialization_uow_factory"].default is Parameter.empty
    assert "ai_run_uow_factory" not in parameters
    assert "project_uow_factory" not in parameters
    assert "create_preview" not in parameters
    assert "decide_preview" not in parameters
