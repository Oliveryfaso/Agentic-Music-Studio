from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.project_reads import (
    DeliveryAsset,
    ListProjects,
    ProjectRunSummary,
    ProjectSummary,
    ProjectWorkspace,
    ReadProjectWorkspace,
    ReadRevisionStudio,
    RevisionStudio,
    RevisionSummary,
)
from motif_forge.application.storage import StorageRootSnapshot
from motif_forge.domain.ai_runs import AIRunStatus
from motif_forge.domain.ir import ArrangementIR
from motif_forge.domain.media_jobs import ArtifactAvailability
from motif_forge.domain.storage import StorageRootHealth
from pydantic import ValidationError


def uid(value: int) -> UUID:
    return UUID(int=value)


NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


class FakeProjectReadStore:
    def __init__(self) -> None:
        self.list_limit: int | None = None
        self.projects: tuple[ProjectSummary, ...] = ()
        self.workspace: ProjectWorkspace | None = None
        self.studio: RevisionStudio | None = None

    async def list_projects(self, *, limit: int) -> tuple[ProjectSummary, ...]:
        self.list_limit = limit
        return self.projects

    async def read_project(self, project_id: UUID) -> ProjectWorkspace | None:
        if self.workspace and self.workspace.project_id == project_id:
            return self.workspace
        return None

    async def read_revision_studio(
        self, *, project_id: UUID, revision_id: UUID
    ) -> RevisionStudio | None:
        if (
            self.studio
            and self.studio.project_id == project_id
            and self.studio.revision_id == revision_id
        ):
            return self.studio
        return None


def run_summary(run_id: int, status: AIRunStatus, minutes_ago: int) -> ProjectRunSummary:
    return ProjectRunSummary(
        run_id=uid(run_id), status=status, updated_at=NOW - timedelta(minutes=minutes_ago)
    )


def revision_summary(revision_id: int, minutes_ago: int) -> RevisionSummary:
    return RevisionSummary(
        revision_id=uid(revision_id), parent_revision_id=None, source_run_id=None,
        reason_code="project-created", author_kind="human", created_by="local-user",
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_project_list_passes_bounded_limit_and_preserves_store_order() -> None:
    store = FakeProjectReadStore()
    store.projects = (
        ProjectSummary(
            project_id=uid(2), name="Newest", status="active", updated_at=NOW,
            active_branch_id=uid(20), head_revision_id=uid(21),
            latest_run=run_summary(22, AIRunStatus.SUCCEEDED, 0),
            has_playable_revision=True,
        ),
        ProjectSummary(
            project_id=uid(1), name="Older", status="active",
            updated_at=NOW - timedelta(days=1), active_branch_id=uid(10),
            head_revision_id=uid(11), latest_run=None, has_playable_revision=False,
        ),
    )

    result = await ListProjects(store)(limit=2)

    assert store.list_limit == 2
    assert tuple(item.name for item in result) == ("Newest", "Older")
    with pytest.raises(ApplicationError, match="PROJECT_LIST_LIMIT_INVALID"):
        await ListProjects(store)(limit=51)


@pytest.mark.asyncio
async def test_workspace_adds_safe_storage_health_and_exposes_recoverable_run() -> None:
    store = FakeProjectReadStore()
    store.workspace = ProjectWorkspace(
        project_id=uid(1), name="Workspace", status="active", updated_at=NOW,
        active_branch_id=uid(2), head_revision_id=uid(4),
        revisions=(revision_summary(4, 0), revision_summary(3, 5)),
        runs=(
            run_summary(8, AIRunStatus.SUCCEEDED, 0),
            run_summary(7, AIRunStatus.WAITING_APPROVAL, 10),
        ),
        recoverable_run=run_summary(7, AIRunStatus.WAITING_APPROVAL, 10),
    )
    def inspect_root() -> StorageRootSnapshot:
        return StorageRootSnapshot(StorageRootHealth.READ_ONLY, True, 987_654)

    result = await ReadProjectWorkspace(store, inspect_root)(uid(1))

    assert result.head_revision_id == uid(4)
    assert tuple(item.revision_id for item in result.revisions) == (uid(4), uid(3))
    assert result.recoverable_run and result.recoverable_run.run_id == uid(7)
    assert result.storage_root_status is StorageRootHealth.READ_ONLY
    assert "free_bytes" not in result.model_dump(mode="json")


@pytest.mark.asyncio
async def test_missing_project_and_wrong_revision_lineage_are_not_found() -> None:
    store = FakeProjectReadStore()

    with pytest.raises(ApplicationError, match="PROJECT_NOT_FOUND"):
        await ReadProjectWorkspace(store, lambda: StorageRootSnapshot(
            StorageRootHealth.READY, True, 1
        ))(uid(1))
    with pytest.raises(ApplicationError, match="REVISION_NOT_FOUND"):
        await ReadRevisionStudio(store)(project_id=uid(1), revision_id=uid(99))


def test_revision_studio_strictly_validates_ir_and_exposes_safe_delivery_metadata() -> None:
    asset = DeliveryAsset(
        artifact_id=uid(40), quality_profile="delivery-mp3.v1", media_type="audio/mpeg",
        availability=ArtifactAvailability.AVAILABLE, byte_size=1234,
        duration_milliseconds=60_000,
    )
    studio = RevisionStudio(
        project_id=uid(1), revision_id=uid(3), parent_revision_id=uid(2),
        source_run_id=uid(8), reason_code="generate", author_kind="agent",
        created_by="generate-worker", created_at=NOW,
        arrangement_ir=ArrangementIR(project_id=uid(1)), delivery_assets=(asset,),
        bundle_id=uid(50),
    )

    serialized = studio.model_dump(mode="json")
    assert serialized["delivery_assets"] == [asset.model_dump(mode="json")]
    assert "storage_key" not in str(serialized)
    assert "storage_prefix" not in str(serialized)
    assert "worker_payload" not in str(serialized)
    with pytest.raises(ValidationError):
        RevisionStudio.model_validate({
            **serialized,
            "arrangement_ir": {
                **serialized["arrangement_ir"],
                "sample_rate": "48000",
            },
        })
