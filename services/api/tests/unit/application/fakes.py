from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from motif_forge.application.ports import IdempotencyHit
from motif_forge.domain.commands import EditorCommand
from motif_forge.domain.revisions import (
    CandidateSnapshot,
    PreviewCandidate,
    ProjectBranch,
    ProjectRootState,
    Revision,
)


class FakeTransaction:
    def __init__(self) -> None:
        self.roots: dict[UUID, ProjectRootState] = {}
        self.branches: dict[UUID, ProjectBranch] = {}
        self.revisions: dict[UUID, Revision] = {}
        self.candidate_snapshots: dict[UUID, CandidateSnapshot] = {}
        self.previews: dict[UUID, PreviewCandidate] = {}
        self.idempotency: dict[tuple[str, str], IdempotencyHit] = {}
        self.command_batches: list[tuple[Revision, tuple[EditorCommand, ...]]] = []
        self.materializations: list[tuple[Revision, UUID, UUID]] = []
        self.approvals: list[tuple[UUID, str, str, datetime]] = []
        self.audit_events: list[tuple[str, UUID]] = []
        self.enter_count = 0
        self.exit_errors: list[type[BaseException] | None] = []

    def __call__(self) -> FakeTransaction:
        return self

    async def __aenter__(self) -> Self:
        self.enter_count += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_errors.append(exc_type)

    async def get_idempotency(
        self, *, operation: str, key: str, request_hash: str
    ) -> IdempotencyHit | None:
        del request_hash
        return self.idempotency.get((operation, key))

    async def save_idempotency(
        self,
        *,
        operation: str,
        key: str,
        request_hash: str,
        resource_id: UUID,
        result_payload: dict[str, object],
    ) -> None:
        self.idempotency[(operation, key)] = IdempotencyHit(
            resource_id, request_hash, result_payload
        )

    async def get_project_root(self, project_id: UUID) -> ProjectRootState | None:
        return self.roots.get(project_id)

    async def insert_project_root(self, *, name: str, root: ProjectRootState) -> None:
        del name
        self.roots[root.project_id] = root
        self.branches[root.branch.branch_id] = root.branch
        self.revisions[root.revision.revision_id] = root.revision

    async def lock_branch(self, *, project_id: UUID, branch_id: UUID) -> ProjectBranch | None:
        branch = self.branches.get(branch_id)
        return branch if branch is not None and branch.project_id == project_id else None

    async def get_revision(self, revision_id: UUID) -> Revision | None:
        return self.revisions.get(revision_id)

    async def get_candidate_snapshot(self, candidate_snapshot_id: UUID) -> CandidateSnapshot | None:
        return self.candidate_snapshots.get(candidate_snapshot_id)

    async def insert_candidate_preview(
        self, *, snapshot: CandidateSnapshot, preview: PreviewCandidate
    ) -> None:
        self.candidate_snapshots[snapshot.candidate_snapshot_id] = snapshot
        self.previews[preview.preview_id] = preview

    async def lock_preview(self, preview_id: UUID) -> PreviewCandidate | None:
        return self.previews.get(preview_id)

    async def update_preview(self, preview: PreviewCandidate) -> None:
        self.previews[preview.preview_id] = preview

    async def insert_revision(
        self,
        *,
        revision: Revision,
        commands: tuple[EditorCommand, ...],
        idempotency_key: str,
    ) -> None:
        del idempotency_key
        self.revisions[revision.revision_id] = revision
        self.command_batches.append((revision, commands))

    async def insert_materialized_revision(
        self,
        *,
        revision: Revision,
        snapshot: CandidateSnapshot,
        preview: PreviewCandidate,
        idempotency_key: str,
        command_id: UUID,
    ) -> None:
        del idempotency_key, command_id
        self.revisions[revision.revision_id] = revision
        self.materializations.append((revision, snapshot.candidate_snapshot_id, preview.preview_id))

    async def insert_approval(
        self,
        *,
        approval_id: UUID,
        preview: PreviewCandidate,
        decision: str,
        actor_id: str,
        payload_hash: str,
        decided_at: datetime,
    ) -> None:
        del payload_hash
        self.approvals.append((approval_id, decision, actor_id, decided_at))

    async def advance_branch_head(
        self, *, branch_id: UUID, expected_head_id: UUID, new_head_id: UUID
    ) -> bool:
        branch = self.branches[branch_id]
        if branch.head_revision_id != expected_head_id:
            return False
        self.branches[branch_id] = branch.model_copy(update={"head_revision_id": new_head_id})
        return True

    async def insert_audit_event(
        self,
        *,
        event_id: UUID,
        project_id: UUID,
        actor_id: str,
        event_type: str,
        resource_id: UUID,
        payload: dict[str, object],
    ) -> None:
        del event_id, project_id, actor_id, payload
        self.audit_events.append((event_type, resource_id))
