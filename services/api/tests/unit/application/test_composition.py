from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from motif_forge.application.composition import (
    PrepareDeterministicCompositionPreview,
    PrepareDeterministicCompositionPreviewRequest,
)
from motif_forge.application.previews import (
    DecidePreview,
    DecidePreviewRequest,
    PreviewDecision,
)
from motif_forge.application.projects import CreateProject, CreateProjectRequest
from motif_forge.domain.revisions import ChangeImpact, PreviewStatus

from .fakes import FakeTransaction

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_from_zero_composition_requires_preview_approval_before_revision() -> None:
    transaction = FakeTransaction()
    root = await CreateProject(transaction)(
        CreateProjectRequest(
            name="S1 Composition", actor_id="local-user", idempotency_key="s1-create-001"
        )
    )
    request = PrepareDeterministicCompositionPreviewRequest(
        project_id=root.project_id,
        branch_id=root.active_branch_id,
        base_revision_id=root.root_revision_id,
        seed=20260812,
        actor_id="agent:deterministic-composer",
        idempotency_key="s1-preview-001",
    )

    prepared = await PrepareDeterministicCompositionPreview(transaction, clock=lambda: NOW)(request)

    assert prepared.status is PreviewStatus.PENDING
    assert prepared.actual_change_impact is ChangeImpact.L3
    assert prepared.duration_seconds == pytest.approx(72.0)
    assert transaction.branches[root.active_branch_id].head_revision_id == root.root_revision_id
    assert len(transaction.revisions) == 1

    approved = await DecidePreview(transaction, clock=lambda: NOW + timedelta(minutes=1))(
        DecidePreviewRequest(
            preview_id=prepared.preview_id,
            decision=PreviewDecision.APPROVE,
            actor_id="local-user",
            approval_assertion="approved after listening to the S1 preview",
            idempotency_key="s1-approve-001",
        )
    )

    assert approved.status is PreviewStatus.APPROVED
    assert approved.revision_id is not None
    assert transaction.branches[root.active_branch_id].head_revision_id == approved.revision_id
    revision = transaction.revisions[approved.revision_id]
    assert revision.arrangement_ir == prepared.arrangement
    assert revision.change_impact_actual is ChangeImpact.L3
    assert len(transaction.approvals) == 1


@pytest.mark.asyncio
async def test_prepare_composition_preview_is_idempotent() -> None:
    transaction = FakeTransaction()
    root = await CreateProject(transaction)(
        CreateProjectRequest(
            name="S1 Composition", actor_id="local-user", idempotency_key="s1-create-001"
        )
    )
    request = PrepareDeterministicCompositionPreviewRequest(
        project_id=root.project_id,
        branch_id=root.active_branch_id,
        base_revision_id=root.root_revision_id,
        seed=9,
        actor_id="agent:deterministic-composer",
        idempotency_key="s1-preview-001",
    )
    prepare = PrepareDeterministicCompositionPreview(transaction, clock=lambda: NOW)

    first = await prepare(request)
    replay = await prepare(request)

    assert replay.preview_id == first.preview_id
    assert replay.replayed is True
    assert len(transaction.previews) == 1
    assert len(transaction.candidate_snapshots) == 1
