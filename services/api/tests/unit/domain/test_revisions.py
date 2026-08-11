from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from motif_forge.domain import (
    ArrangementIR,
    CandidateSnapshot,
    ChangeImpact,
    ProjectBranch,
    Section,
    arrangement_content_hash,
    create_candidate_snapshot,
    create_preview_candidate,
    create_root_state,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


def test_root_state_has_one_authoritative_branch_head_and_matching_hash() -> None:
    root = create_root_state(
        uid(1),
        created_by="test-user",
        branch_id=uid(2),
        revision_id=uid(3),
        created_at=NOW,
    )

    assert root.active_branch_id == root.branch.branch_id
    assert root.branch.head_revision_id == root.revision.revision_id
    assert root.revision.parent_revision_id is None
    assert root.revision.content_hash == arrangement_content_hash(root.revision.arrangement_ir)


def test_candidate_and_preview_keep_snapshot_separate_from_revision() -> None:
    root = create_root_state(
        uid(1),
        created_by="test-user",
        branch_id=uid(2),
        revision_id=uid(3),
        created_at=NOW,
    )
    candidate_ir = ArrangementIR(
        project_id=uid(1),
        sections=(Section(section_id=uid(4), start_tick=0, end_tick=1_920, label="A"),),
    )
    snapshot = create_candidate_snapshot(
        base_revision=root.revision,
        candidate_ir=candidate_ir,
        candidate_id=uid(5),
        candidate_snapshot_id=uid(6),
        created_at=NOW,
    )
    preview = create_preview_candidate(
        snapshot=snapshot,
        branch=root.branch,
        actual_change_impact=ChangeImpact.L3,
        preview_id=uid(7),
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )

    assert preview.candidate_snapshot_id == snapshot.candidate_snapshot_id
    assert preview.base_revision_id == root.branch.head_revision_id
    assert preview.status == "pending"
    assert not hasattr(preview, "arrangement_ir")

    with pytest.raises(ValidationError, match="Instance is frozen"):
        snapshot.candidate_content_hash = "0" * 64  # type: ignore[misc]


def test_candidate_rejects_hash_mismatch() -> None:
    arrangement = ArrangementIR(project_id=uid(1))

    with pytest.raises(ValidationError, match="candidate_content_hash does not match"):
        CandidateSnapshot(
            candidate_snapshot_id=uid(2),
            candidate_id=uid(3),
            project_id=uid(1),
            base_revision_id=uid(4),
            candidate_ir=arrangement,
            candidate_content_hash="0" * 64,
            created_at=NOW,
        )


def test_preview_requires_current_branch_base_and_high_impact() -> None:
    root = create_root_state(uid(1), created_by="test-user", created_at=NOW)
    snapshot = create_candidate_snapshot(
        base_revision=root.revision,
        candidate_ir=root.revision.arrangement_ir,
        candidate_id=uid(5),
        created_at=NOW,
    )
    stale_branch = ProjectBranch(
        branch_id=root.branch.branch_id,
        project_id=root.project_id,
        name="main",
        head_revision_id=uid(99),
        created_from_revision_id=root.revision.revision_id,
        created_at=NOW,
        created_by="test-user",
    )

    with pytest.raises(ValueError, match="snapshot base must equal branch head"):
        create_preview_candidate(
            snapshot=snapshot,
            branch=stale_branch,
            actual_change_impact=ChangeImpact.L2,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="L0/L1 changes commit directly"):
        create_preview_candidate(
            snapshot=snapshot,
            branch=root.branch,
            actual_change_impact=ChangeImpact.L1,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
