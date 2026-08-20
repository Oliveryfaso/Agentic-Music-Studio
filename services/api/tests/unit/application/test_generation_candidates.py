from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.application.errors import ApplicationError
from motif_forge.application.generation_candidates import (
    CreateCandidateSelectionPreview,
    CreateCandidateSelectionPreviewRequest,
    CreateCompositionCandidate,
    CreateCompositionCandidateRequest,
    MaterializeSelectedCompositionCandidate,
    MaterializeSelectedCompositionCandidateRequest,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunApproval,
    AIRunEvent,
    AIRunStatus,
    CompositionMaterializationReceipt,
    PersistedCompositionPlan,
    approval_assertion_hash,
    composition_plan_content_hash,
)
from motif_forge.domain.candidates import CandidateLabel, derive_candidate_seed

from .fakes import FakeTransaction

NOW = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
PLAN_ASSERTION = "I approve this Plan for two candidate generation."
SELECTION_ASSERTION = "I select candidate B after comparing both previews."


def _brief() -> CompositionBrief:
    return CompositionBrief(
        title="S5 pair",
        purpose="Compare two evidence-grounded instrumental candidates",
        style="synth_ambient",
        duration_seconds=60,
        meter="4/4",
        target_bpm=80,
        target_key="C major",
        moods=("focused",),
    )


class CandidateTransaction(FakeTransaction):
    def __init__(self) -> None:
        super().__init__()
        self.run: AIRun | None = None
        self.plan: PersistedCompositionPlan | None = None
        self.approval: AIRunApproval | None = None
        self.receipts: dict[int, CompositionMaterializationReceipt] = {}
        self.run_events: list[AIRunEvent] = []

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await super().__aexit__(exc_type, exc, traceback)

    async def lock_ai_run(self, run_id: UUID) -> AIRun:
        assert self.run is not None and self.run.run_id == run_id
        return self.run

    async def read_ai_run_approval(self, run_id: UUID) -> AIRunApproval | None:
        assert self.run is not None and self.run.run_id == run_id
        return self.approval

    async def read_composition_plan(
        self, *, plan_id: UUID, run_id: UUID
    ) -> PersistedCompositionPlan:
        assert self.plan is not None
        assert self.plan.plan_id == plan_id and self.plan.run_id == run_id
        return self.plan

    async def read_materialization_receipt(
        self, *, run_id: UUID, plan_id: UUID, plan_hash: str, seed: int
    ) -> CompositionMaterializationReceipt | None:
        del run_id, plan_id, plan_hash
        return self.receipts.get(seed)

    async def insert_materialization_receipt(
        self, receipt: CompositionMaterializationReceipt, event: AIRunEvent
    ) -> None:
        self.receipts[receipt.seed] = receipt
        self.run_events.append(event)

    async def record_ai_run_event(self, event: AIRunEvent) -> AIRunEvent:
        if any(
            previous.event_type == event.event_type
            and previous.dedupe_key == event.dedupe_key
            for previous in self.run_events
        ):
            return next(
                previous
                for previous in self.run_events
                if previous.event_type == event.event_type
                and previous.dedupe_key == event.dedupe_key
            )
        stored = event.model_copy(update={"sequence": len(self.run_events) + 1})
        self.run_events.append(stored)
        return stored


async def _fixture() -> tuple[CandidateTransaction, AIRun, PersistedCompositionPlan]:
    transaction = CandidateTransaction()
    project = await CreateProject(transaction)(
        CreateProjectRequest(
            name="S5 candidate test",
            actor_id="human",
            idempotency_key="s5-project",
        )
    )
    brief = _brief()
    plan = build_fallback_plan(brief)
    plan_hash = composition_plan_content_hash(plan)
    run = AIRun(
        run_id=uuid4(),
        project_id=project.project_id,
        branch_id=project.active_branch_id,
        base_revision_id=project.root_revision_id,
        thread_id="s5-candidate-thread",
        brief=brief.model_dump(mode="json"),
        status=AIRunStatus.MATERIALIZING,
        version=2,
        approval_assertion_hash=approval_assertion_hash(PLAN_ASSERTION),
        created_at=NOW,
        updated_at=NOW,
    )
    persisted = PersistedCompositionPlan(
        plan_id=uuid4(),
        run_id=run.run_id,
        plan=plan,
        content_hash=plan_hash,
        provider="deterministic-fallback",
        model="none",
        prompt_version="composition-planner.v1",
        schema_version=plan.schema_version,
        style_pack_version="style:synth-ambient:v1",
        fallback_reason="no-key",
        created_at=NOW,
    )
    transaction.run = run
    transaction.plan = persisted
    transaction.approval = AIRunApproval(
        approval_id=uuid4(),
        run_id=run.run_id,
        assertion_hash=approval_assertion_hash(PLAN_ASSERTION),
        decision="approve",
        actor_id="human",
        expected_plan_content_hash=plan_hash,
        interrupt_ref="s5-plan-approval",
        decided_at=NOW,
    )
    return transaction, run, persisted


@pytest.mark.asyncio
async def test_two_labels_create_distinct_stable_snapshots_without_revision() -> None:
    transaction, run, plan = await _fixture()
    service = CreateCompositionCandidate(transaction, clock=lambda: NOW)

    results = []
    for label in (CandidateLabel.A, CandidateLabel.B):
        request = CreateCompositionCandidateRequest(
            run_id=run.run_id,
            project_id=run.project_id,
            branch_id=run.branch_id,
            base_revision_id=run.base_revision_id,
            plan_id=plan.plan_id,
            expected_plan_hash=plan.content_hash,
            label=label,
            seed=derive_candidate_seed(0, label),
        )
        results.append(await service(request))
    replay = await service(
        CreateCompositionCandidateRequest(
            run_id=run.run_id,
            project_id=run.project_id,
            branch_id=run.branch_id,
            base_revision_id=run.base_revision_id,
            plan_id=plan.plan_id,
            expected_plan_hash=plan.content_hash,
            label=CandidateLabel.A,
            seed=0,
        )
    )

    assert results[0].candidate_id != results[1].candidate_id
    assert replay.candidate_snapshot_id == results[0].candidate_snapshot_id
    assert replay.replayed is True
    assert len(transaction.candidate_snapshots) == 2
    assert len(transaction.revisions) == 1
    assert [event.event_type for event in transaction.run_events] == [
        "composition.candidate-created",
        "composition.candidate-created",
    ]


@pytest.mark.asyncio
async def test_only_selected_preview_materializes_one_revision_and_replays() -> None:
    transaction, run, plan = await _fixture()
    create = CreateCompositionCandidate(transaction, clock=lambda: NOW)
    candidates = [
        await create(
            CreateCompositionCandidateRequest(
                run_id=run.run_id,
                project_id=run.project_id,
                branch_id=run.branch_id,
                base_revision_id=run.base_revision_id,
                plan_id=plan.plan_id,
                expected_plan_hash=plan.content_hash,
                label=label,
                seed=derive_candidate_seed(0, label),
            )
        )
        for label in (CandidateLabel.A, CandidateLabel.B)
    ]
    preview_service = CreateCandidateSelectionPreview(transaction, clock=lambda: NOW)
    previews = [
        await preview_service(
            CreateCandidateSelectionPreviewRequest(
                run_id=run.run_id,
                project_id=run.project_id,
                branch_id=run.branch_id,
                base_revision_id=run.base_revision_id,
                candidate_snapshot_id=item.candidate_snapshot_id,
                preview_artifact_id=uuid4(),
                evidence_refs=(f"candidate:{item.label}:score",),
            )
        )
        for item in candidates
    ]
    selected = candidates[1]
    preview = previews[1]
    request = MaterializeSelectedCompositionCandidateRequest(
        run_id=run.run_id,
        project_id=run.project_id,
        branch_id=run.branch_id,
        base_revision_id=run.base_revision_id,
        plan_id=plan.plan_id,
        expected_plan_hash=plan.content_hash,
        selected_preview_id=preview.preview_id,
        expected_candidate_content_hash=selected.candidate_content_hash,
        seed=selected.seed,
        actor_id="human",
        selection_assertion=SELECTION_ASSERTION,
        idempotency_key="select-candidate-b",
    )
    materialize = MaterializeSelectedCompositionCandidate(transaction, clock=lambda: NOW)

    first = await materialize(request)
    replay = await materialize(request)

    assert first.revision_id == replay.revision_id
    assert replay.replayed is True
    assert len(transaction.revisions) == 2
    assert len(transaction.materializations) == 1
    assert transaction.branches[run.branch_id].head_revision_id == first.revision_id


@pytest.mark.asyncio
async def test_rejected_plan_and_foreign_run_preview_fail_without_revision() -> None:
    transaction, run, plan = await _fixture()
    assert transaction.approval is not None
    transaction.approval = transaction.approval.model_copy(update={"decision": "reject"})
    transaction.run = run.model_copy(update={"status": AIRunStatus.REJECTED})
    request = CreateCompositionCandidateRequest(
        run_id=run.run_id,
        project_id=run.project_id,
        branch_id=run.branch_id,
        base_revision_id=run.base_revision_id,
        plan_id=plan.plan_id,
        expected_plan_hash=plan.content_hash,
        label=CandidateLabel.A,
        seed=0,
    )
    with pytest.raises(ApplicationError, match="requires the approved Plan"):
        await CreateCompositionCandidate(transaction, clock=lambda: NOW)(request)
    assert len(transaction.revisions) == 1

    transaction.approval = transaction.approval.model_copy(update={"decision": "approve"})
    transaction.run = run
    candidate = await CreateCompositionCandidate(transaction, clock=lambda: NOW)(request)
    preview = await CreateCandidateSelectionPreview(transaction, clock=lambda: NOW)(
        CreateCandidateSelectionPreviewRequest(
            run_id=run.run_id,
            project_id=run.project_id,
            branch_id=run.branch_id,
            base_revision_id=run.base_revision_id,
            candidate_snapshot_id=candidate.candidate_snapshot_id,
            preview_artifact_id=uuid4(),
            evidence_refs=("candidate:a:preview",),
        )
    )
    transaction.previews[preview.preview_id] = transaction.previews[
        preview.preview_id
    ].model_copy(update={"source_run_id": uuid4()})
    with pytest.raises(ApplicationError, match="does not match the AI run"):
        await MaterializeSelectedCompositionCandidate(transaction, clock=lambda: NOW)(
            MaterializeSelectedCompositionCandidateRequest(
                run_id=run.run_id,
                project_id=run.project_id,
                branch_id=run.branch_id,
                base_revision_id=run.base_revision_id,
                plan_id=plan.plan_id,
                expected_plan_hash=plan.content_hash,
                selected_preview_id=preview.preview_id,
                expected_candidate_content_hash=candidate.candidate_content_hash,
                seed=candidate.seed,
                actor_id="human",
                selection_assertion=SELECTION_ASSERTION,
                idempotency_key="select-foreign-preview",
            )
        )
    assert len(transaction.revisions) == 1
