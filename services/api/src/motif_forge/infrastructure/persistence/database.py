"""Async PostgreSQL Unit of Work for project and Revision writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from motif_forge.application.ports import IdempotencyHit
from motif_forge.domain.commands import EDITOR_COMMAND_ADAPTER, EditorCommand
from motif_forge.domain.ir import ArrangementIR
from motif_forge.domain.revisions import (
    AuthorKind,
    CandidateSnapshot,
    ChangeImpact,
    PreviewCandidate,
    ProjectBranch,
    ProjectRootState,
    Revision,
    VersionRefs,
)
from motif_forge.infrastructure.persistence.tables import (
    ApprovalRow,
    AuditEventRow,
    BranchRow,
    CandidateSnapshotRow,
    CommandBatchRow,
    IdempotencyRow,
    PreviewCandidateRow,
    ProjectRow,
    RevisionCommandRow,
    RevisionRow,
)

SessionFactory = async_sessionmaker[AsyncSession]


def normalize_postgres_dsn(database_url: str) -> str:
    """Normalize the shared raw PostgreSQL DSN for SQLAlchemy's async psycopg driver."""

    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    elif url.drivername != "postgresql+psycopg":
        raise ValueError("database_url must be a PostgreSQL DSN")
    return url.render_as_string(hide_password=False)


def create_postgres_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine and reject accidental SQLite test substitutes."""

    return create_async_engine(normalize_postgres_dsn(database_url), echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class PostgresUnitOfWork:
    """Callable transaction factory suitable for Application use cases."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresTransaction:
        return PostgresTransaction(self._session_factory())


class PostgresTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()

    async def get_idempotency(
        self, *, operation: str, key: str, request_hash: str
    ) -> IdempotencyHit | None:
        del request_hash  # The Application compares its fingerprint with the stored value.
        statement = select(
            IdempotencyRow.resource_id,
            IdempotencyRow.request_hash,
            IdempotencyRow.result_payload,
        ).where(
            IdempotencyRow.operation == operation,
            IdempotencyRow.idempotency_key == key,
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        return IdempotencyHit(
            resource_id=row.resource_id,
            request_hash=row.request_hash,
            result_payload=row.result_payload,
        )

    async def save_idempotency(
        self,
        *,
        operation: str,
        key: str,
        request_hash: str,
        resource_id: UUID,
        result_payload: dict[str, object],
    ) -> None:
        await self._session.execute(
            insert(IdempotencyRow).values(
                operation=operation,
                idempotency_key=key,
                request_hash=request_hash,
                resource_id=resource_id,
                result_payload=result_payload,
                created_at=datetime.now(UTC),
            )
        )

    async def get_project_root(self, project_id: UUID) -> ProjectRootState | None:
        project = (
            await self._session.execute(
                select(ProjectRow.active_branch_id).where(ProjectRow.id == project_id)
            )
        ).one_or_none()
        if project is None:
            return None
        branch_row = (
            await self._session.execute(
                select(BranchRow).where(
                    BranchRow.id == project.active_branch_id,
                    BranchRow.project_id == project_id,
                )
            )
        ).scalar_one_or_none()
        if branch_row is None:
            return None
        revision = await self.get_revision(branch_row.base_revision_id)
        if revision is None:
            return None
        # This method returns the immutable creation snapshot, not the branch's current head.
        branch = ProjectBranch(
            branch_id=branch_row.id,
            project_id=branch_row.project_id,
            name=branch_row.name,
            head_revision_id=branch_row.base_revision_id,
            created_from_revision_id=branch_row.base_revision_id,
            created_at=branch_row.created_at,
            created_by=branch_row.created_by,
        )
        return ProjectRootState(
            project_id=project_id,
            active_branch_id=branch.branch_id,
            branch=branch,
            revision=revision,
        )

    async def insert_project_root(self, *, name: str, root: ProjectRootState) -> None:
        revision = root.revision
        branch = root.branch
        await self._session.execute(
            insert(ProjectRow).values(
                id=root.project_id,
                name=name,
                active_branch_id=root.active_branch_id,
                status="active",
                created_at=revision.created_at,
                updated_at=revision.created_at,
            )
        )
        await self._session.execute(insert(RevisionRow).values(**_revision_values(revision)))
        await self._session.execute(
            insert(BranchRow).values(
                id=branch.branch_id,
                project_id=branch.project_id,
                name=branch.name,
                head_revision_id=branch.head_revision_id,
                base_revision_id=branch.created_from_revision_id,
                created_at=branch.created_at,
                updated_at=branch.created_at,
                created_by=branch.created_by,
            )
        )

    async def lock_branch(self, *, project_id: UUID, branch_id: UUID) -> ProjectBranch | None:
        statement = (
            select(BranchRow)
            .where(BranchRow.id == branch_id, BranchRow.project_id == project_id)
            .with_for_update()
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        return ProjectBranch(
            branch_id=row.id,
            project_id=row.project_id,
            name=row.name,
            head_revision_id=row.head_revision_id,
            created_from_revision_id=row.base_revision_id,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    async def get_revision(self, revision_id: UUID) -> Revision | None:
        row = (
            await self._session.execute(select(RevisionRow).where(RevisionRow.id == revision_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        return _revision_from_row(row)

    async def list_revision_commands(self, revision_id: UUID) -> tuple[EditorCommand, ...]:
        rows = (
            await self._session.execute(
                select(RevisionCommandRow)
                .where(RevisionCommandRow.revision_id == revision_id)
                .order_by(RevisionCommandRow.client_sequence)
            )
        ).scalars()
        return tuple(
            EDITOR_COMMAND_ADAPTER.validate_python(
                {
                    "command_id": row.command_id,
                    "command_type": row.command_type,
                    "schema_version": row.schema_version,
                    "payload": row.payload,
                    "selection": row.selection,
                    "actor_kind": row.actor_kind,
                    "client_sequence": row.client_sequence,
                }
            )
            for row in rows
        )

    async def get_candidate_snapshot(self, candidate_snapshot_id: UUID) -> CandidateSnapshot | None:
        row = (
            await self._session.execute(
                select(CandidateSnapshotRow).where(CandidateSnapshotRow.id == candidate_snapshot_id)
            )
        ).scalar_one_or_none()
        return None if row is None else _candidate_snapshot_from_row(row)

    async def insert_candidate_snapshot(self, snapshot: CandidateSnapshot) -> None:
        existing = await self.get_candidate_snapshot(snapshot.candidate_snapshot_id)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("candidate Snapshot identity contains divergent facts")
            return
        await self._session.execute(
            insert(CandidateSnapshotRow).values(**_candidate_snapshot_values(snapshot))
        )

    async def insert_candidate_preview(
        self, *, snapshot: CandidateSnapshot, preview: PreviewCandidate
    ) -> None:
        await self.insert_candidate_snapshot(snapshot)
        await self._session.execute(
            insert(PreviewCandidateRow).values(**_preview_candidate_values(preview))
        )

    async def lock_preview(self, preview_id: UUID) -> PreviewCandidate | None:
        row = (
            await self._session.execute(
                select(PreviewCandidateRow)
                .where(PreviewCandidateRow.id == preview_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return None if row is None else _preview_candidate_from_row(row)

    async def update_preview(self, preview: PreviewCandidate) -> None:
        await self._session.execute(
            update(PreviewCandidateRow)
            .where(PreviewCandidateRow.id == preview.preview_id)
            .values(
                status=preview.status.value,
                approved_revision_id=preview.approved_revision_id,
                decision_by=preview.decision_by,
                decision_at=preview.decision_at,
            )
        )

    async def insert_revision(
        self,
        *,
        revision: Revision,
        commands: tuple[EditorCommand, ...],
        idempotency_key: str,
    ) -> None:
        batch_id = revision.command_batch_id
        if batch_id is None or revision.parent_revision_id is None:
            raise ValueError("committed command revision requires batch and parent IDs")
        await self._session.execute(
            insert(CommandBatchRow).values(
                id=batch_id,
                project_id=revision.project_id,
                branch_id=revision.created_on_branch_id,
                base_revision_id=revision.parent_revision_id,
                resulting_revision_id=revision.revision_id,
                actor_kind=revision.author_kind.value,
                actor_id=revision.created_by,
                predicted_impact=int(revision.change_impact_predicted),
                actual_impact=int(revision.change_impact_actual),
                idempotency_key=idempotency_key,
                created_at=revision.created_at,
            )
        )
        await self._session.execute(insert(RevisionRow).values(**_revision_values(revision)))
        for command in commands:
            await self._session.execute(
                insert(RevisionCommandRow).values(
                    revision_id=revision.revision_id,
                    command_batch_id=batch_id,
                    command_id=command.command_id,
                    command_type=command.command_type,
                    schema_version=command.schema_version,
                    payload=command.payload.model_dump(mode="json"),
                    selection=command.selection.model_dump(mode="json"),
                    actor_kind=command.actor_kind,
                    client_sequence=command.client_sequence,
                )
            )

    async def insert_materialized_revision(
        self,
        *,
        revision: Revision,
        snapshot: CandidateSnapshot,
        preview: PreviewCandidate,
        idempotency_key: str,
        command_id: UUID,
    ) -> None:
        batch_id = revision.command_batch_id
        if batch_id is None or revision.parent_revision_id is None:
            raise ValueError("materialized revision requires batch and parent IDs")
        await self._session.execute(
            insert(CommandBatchRow).values(
                id=batch_id,
                project_id=revision.project_id,
                branch_id=revision.created_on_branch_id,
                base_revision_id=revision.parent_revision_id,
                resulting_revision_id=revision.revision_id,
                actor_kind=revision.author_kind.value,
                actor_id=revision.created_by,
                predicted_impact=int(revision.change_impact_predicted),
                actual_impact=int(revision.change_impact_actual),
                idempotency_key=idempotency_key,
                created_at=revision.created_at,
            )
        )
        await self._session.execute(insert(RevisionRow).values(**_revision_values(revision)))
        if snapshot.commands:
            commands = snapshot.commands
        else:
            await self._session.execute(
                insert(RevisionCommandRow).values(
                    revision_id=revision.revision_id,
                    command_batch_id=batch_id,
                    command_id=command_id,
                    command_type="materialize_candidate",
                    schema_version="service-command.v1",
                    payload={
                        "candidate_snapshot_id": str(snapshot.candidate_snapshot_id),
                        "candidate_content_hash": snapshot.candidate_content_hash,
                        "preview_id": str(preview.preview_id),
                    },
                    selection={},
                    actor_kind=revision.author_kind.value,
                    client_sequence=0,
                )
            )
            return
        for command in commands:
            await self._session.execute(
                insert(RevisionCommandRow).values(
                    revision_id=revision.revision_id,
                    command_batch_id=batch_id,
                    command_id=command.command_id,
                    command_type=command.command_type,
                    schema_version=command.schema_version,
                    payload=command.payload.model_dump(mode="json"),
                    selection=command.selection.model_dump(mode="json"),
                    actor_kind=command.actor_kind,
                    client_sequence=command.client_sequence,
                )
            )

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
        await self._session.execute(
            insert(ApprovalRow).values(
                id=approval_id,
                project_id=preview.project_id,
                preview_id=preview.preview_id,
                source_run_id=preview.source_run_id,
                decision=decision,
                actor_id=actor_id,
                payload_hash=payload_hash,
                decided_at=decided_at,
            )
        )

    async def advance_branch_head(
        self, *, branch_id: UUID, expected_head_id: UUID, new_head_id: UUID
    ) -> bool:
        result = await self._session.execute(
            update(BranchRow)
            .where(BranchRow.id == branch_id, BranchRow.head_revision_id == expected_head_id)
            .values(head_revision_id=new_head_id, updated_at=datetime.now(UTC))
            .returning(BranchRow.id)
        )
        return result.scalar_one_or_none() is not None

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
        await self._session.execute(
            insert(AuditEventRow).values(
                id=event_id,
                project_id=project_id,
                actor_id=actor_id,
                event_type=event_type,
                resource_id=resource_id,
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )


def _revision_values(revision: Revision) -> dict[str, object]:
    return {
        "id": revision.revision_id,
        "project_id": revision.project_id,
        "parent_id": revision.parent_revision_id,
        "created_on_branch_id": revision.created_on_branch_id,
        "arrangement_ir": revision.arrangement_ir.model_dump(mode="json"),
        "content_hash": revision.content_hash,
        "command_batch_id": revision.command_batch_id,
        "change_impact_predicted": int(revision.change_impact_predicted),
        "change_impact_actual": int(revision.change_impact_actual),
        "author_kind": revision.author_kind.value,
        "created_by": revision.created_by,
        "source_run_id": revision.source_run_id,
        "reason_code": revision.reason_code,
        "versions": revision.versions.model_dump(mode="json"),
        "schema_version": revision.schema_version,
        "created_at": revision.created_at,
    }


def _revision_from_row(row: RevisionRow) -> Revision:
    return Revision(
        revision_id=row.id,
        project_id=row.project_id,
        parent_revision_id=row.parent_id,
        created_on_branch_id=row.created_on_branch_id,
        # JSONB returns JSON-compatible Python values (UUIDs as strings and
        # tuples as lists). Validate through Pydantic's JSON mode so the strict
        # domain model keeps rejecting coercion at ordinary Python boundaries
        # while accepting its canonical persisted representation.
        arrangement_ir=ArrangementIR.model_validate_json(
            json.dumps(row.arrangement_ir), strict=True
        ),
        content_hash=row.content_hash,
        command_batch_id=row.command_batch_id,
        change_impact_predicted=ChangeImpact(row.change_impact_predicted),
        change_impact_actual=ChangeImpact(row.change_impact_actual),
        author_kind=AuthorKind(row.author_kind),
        created_by=row.created_by,
        source_run_id=row.source_run_id,
        reason_code=row.reason_code,
        versions=VersionRefs.model_validate_json(json.dumps(row.versions), strict=True),
        created_at=row.created_at,
    )


def _candidate_snapshot_values(snapshot: CandidateSnapshot) -> dict[str, object]:
    return {
        "id": snapshot.candidate_snapshot_id,
        "candidate_id": snapshot.candidate_id,
        "project_id": snapshot.project_id,
        "base_revision_id": snapshot.base_revision_id,
        "source_run_id": snapshot.source_run_id,
        "parent_candidate_snapshot_id": snapshot.parent_candidate_snapshot_id,
        "candidate_ir": snapshot.candidate_ir.model_dump(mode="json"),
        "candidate_content_hash": snapshot.candidate_content_hash,
        "commands": [command.model_dump(mode="json") for command in snapshot.commands],
        "command_batch_id": snapshot.command_batch_id,
        "materialization_command_ref": snapshot.materialization_command_ref,
        "structural_diff": [entry.model_dump(mode="json") for entry in snapshot.structural_diff],
        "non_target_preservation_hash": snapshot.non_target_preservation_hash,
        "versions": snapshot.versions.model_dump(mode="json"),
        "schema_version": snapshot.schema_version,
        "created_at": snapshot.created_at,
    }


def _candidate_snapshot_from_row(row: CandidateSnapshotRow) -> CandidateSnapshot:
    return CandidateSnapshot.model_validate_json(
        json.dumps(
            {
                "candidate_snapshot_id": str(row.id),
                "candidate_id": str(row.candidate_id),
                "project_id": str(row.project_id),
                "base_revision_id": str(row.base_revision_id),
                "source_run_id": None if row.source_run_id is None else str(row.source_run_id),
                "parent_candidate_snapshot_id": (
                    None
                    if row.parent_candidate_snapshot_id is None
                    else str(row.parent_candidate_snapshot_id)
                ),
                "candidate_ir": row.candidate_ir,
                "candidate_content_hash": row.candidate_content_hash,
                "commands": row.commands,
                "command_batch_id": (
                    None if row.command_batch_id is None else str(row.command_batch_id)
                ),
                "materialization_command_ref": (
                    None
                    if row.materialization_command_ref is None
                    else str(row.materialization_command_ref)
                ),
                "structural_diff": row.structural_diff,
                "non_target_preservation_hash": row.non_target_preservation_hash,
                "versions": row.versions,
                "schema_version": row.schema_version,
                "created_at": row.created_at.isoformat(),
            }
        ),
        strict=True,
    )


def _preview_candidate_values(preview: PreviewCandidate) -> dict[str, object]:
    payload = preview.model_dump(mode="json")
    return {
        "id": preview.preview_id,
        **{key: value for key, value in payload.items() if key != "preview_id"},
    }


def _preview_candidate_from_row(row: PreviewCandidateRow) -> PreviewCandidate:
    return PreviewCandidate.model_validate_json(
        json.dumps(
            {
                "preview_id": str(row.id),
                "project_id": str(row.project_id),
                "branch_id": str(row.branch_id),
                "base_revision_id": str(row.base_revision_id),
                "candidate_snapshot_id": str(row.candidate_snapshot_id),
                "candidate_content_hash": row.candidate_content_hash,
                "structural_diff": row.structural_diff,
                "actual_change_impact": row.actual_change_impact,
                "non_target_preservation_hash": row.non_target_preservation_hash,
                "preview_artifact_ids": row.preview_artifact_ids,
                "analysis_artifact_ids": row.analysis_artifact_ids,
                "evidence_refs": row.evidence_refs,
                "source_run_id": None if row.source_run_id is None else str(row.source_run_id),
                "status": row.status,
                "approved_revision_id": (
                    None if row.approved_revision_id is None else str(row.approved_revision_id)
                ),
                "decision_by": row.decision_by,
                "decision_at": None if row.decision_at is None else row.decision_at.isoformat(),
                "schema_version": row.schema_version,
                "created_at": row.created_at.isoformat(),
                "expires_at": row.expires_at.isoformat(),
            }
        ),
        strict=True,
    )
