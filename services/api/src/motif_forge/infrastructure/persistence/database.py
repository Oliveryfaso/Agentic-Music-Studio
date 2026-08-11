"""Async PostgreSQL Unit of Work for project and Revision writes."""

from __future__ import annotations

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
from motif_forge.domain.commands import EditorCommand
from motif_forge.domain.ir import ArrangementIR
from motif_forge.domain.revisions import (
    AuthorKind,
    ChangeImpact,
    ProjectBranch,
    ProjectRootState,
    Revision,
    VersionRefs,
)
from motif_forge.infrastructure.persistence.tables import (
    AuditEventRow,
    BranchRow,
    CommandBatchRow,
    IdempotencyRow,
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
        arrangement_ir=ArrangementIR.model_validate(row.arrangement_ir),
        content_hash=row.content_hash,
        command_batch_id=row.command_batch_id,
        change_impact_predicted=ChangeImpact(row.change_impact_predicted),
        change_impact_actual=ChangeImpact(row.change_impact_actual),
        author_kind=AuthorKind(row.author_kind),
        created_by=row.created_by,
        source_run_id=row.source_run_id,
        reason_code=row.reason_code,
        versions=VersionRefs.model_validate(row.versions),
        created_at=row.created_at,
    )
