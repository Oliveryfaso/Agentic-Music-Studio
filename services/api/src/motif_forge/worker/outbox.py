"""Leased PostgreSQL Outbox delivery to the at-least-once media queue."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from langgraph.types import Command
from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult

from motif_forge.domain.media_jobs import WorkerResumePayload
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import OutboxEventRow

MEDIA_DISPATCH_TOPICS = frozenset({"media.job.dispatch.requested", "media.job.retry.requested"})
GRAPH_RESUME_TOPICS = frozenset({"graph.resume.requested"})


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    event_id: UUID
    topic: str
    dedupe_key: str
    payload: dict[str, object]
    attempts: int


class OutboxPublisher(Protocol):
    async def publish(self, message: OutboxMessage) -> None: ...


class OutboxStore(Protocol):
    async def claim_batch(
        self,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
        batch_size: int,
    ) -> tuple[OutboxMessage, ...]: ...

    async def mark_published(
        self, event_id: UUID, *, owner: str, published_at: datetime
    ) -> bool: ...

    async def mark_failed(
        self,
        event_id: UUID,
        *,
        owner: str,
        failed_at: datetime,
        error_code: str,
        attempts: int,
    ) -> bool: ...


class PostgresOutboxStore:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        topics: frozenset[str] = MEDIA_DISPATCH_TOPICS,
        run_type_prefix: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._topics = topics
        self._run_type_prefix = run_type_prefix

    async def claim_batch(
        self,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
        batch_size: int,
    ) -> tuple[OutboxMessage, ...]:
        async with self._session_factory.begin() as session:
            conditions = [
                OutboxEventRow.topic.in_(self._topics),
                OutboxEventRow.available_at <= now,
                or_(
                    OutboxEventRow.status == "pending",
                    (
                        (OutboxEventRow.status == "publishing")
                        & (OutboxEventRow.lease_expires_at <= now)
                    ),
                ),
            ]
            if self._run_type_prefix is not None:
                conditions.append(
                    OutboxEventRow.payload["run_type"].astext.like(f"{self._run_type_prefix}%")
                )
            rows = (
                await session.execute(
                    select(OutboxEventRow)
                    .where(*conditions)
                    .order_by(OutboxEventRow.created_at, OutboxEventRow.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
            claimed: list[OutboxMessage] = []
            for row in rows:
                row.status = "publishing"
                row.lease_owner = owner
                row.lease_expires_at = lease_expires_at
                row.attempts += 1
                claimed.append(
                    OutboxMessage(
                        event_id=row.id,
                        topic=row.topic,
                        dedupe_key=row.dedupe_key,
                        payload=dict(row.payload),
                        attempts=row.attempts,
                    )
                )
            return tuple(claimed)

    async def mark_published(self, event_id: UUID, *, owner: str, published_at: datetime) -> bool:
        async with self._session_factory.begin() as session:
            result = await session.execute(
                update(OutboxEventRow)
                .where(
                    OutboxEventRow.id == event_id,
                    OutboxEventRow.status == "publishing",
                    OutboxEventRow.lease_owner == owner,
                )
                .values(
                    status="published",
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=None,
                    published_at=published_at,
                )
            )
            return bool(cast(CursorResult[Any], result).rowcount)

    async def mark_failed(
        self,
        event_id: UUID,
        *,
        owner: str,
        failed_at: datetime,
        error_code: str,
        attempts: int,
    ) -> bool:
        terminal = attempts >= 20
        delay_seconds = min(2 ** min(attempts, 6), 60)
        async with self._session_factory.begin() as session:
            result = await session.execute(
                update(OutboxEventRow)
                .where(
                    OutboxEventRow.id == event_id,
                    OutboxEventRow.status == "publishing",
                    OutboxEventRow.lease_owner == owner,
                )
                .values(
                    status="failed" if terminal else "pending",
                    available_at=failed_at + timedelta(seconds=delay_seconds),
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=error_code,
                )
            )
            return bool(cast(CursorResult[Any], result).rowcount)


class CeleryMediaJobPublisher:
    def __init__(self, celery_app: Celery, *, queue: str) -> None:
        self._celery_app = celery_app
        self._queue = queue

    async def publish(self, message: OutboxMessage) -> None:
        raw_job_id = message.payload.get("job_id")
        if not isinstance(raw_job_id, str):
            raise ValueError("media Outbox payload is missing job_id")
        job_id = UUID(raw_job_id)
        await asyncio.to_thread(
            self._celery_app.send_task,
            "motif_forge.execute_media_job",
            args=[str(job_id)],
            queue=self._queue,
            task_id=str(message.event_id),
        )


class ParentGraphResumePublisher:
    """Resume only checkpoints belonging to the versioned Parent Graph."""

    def __init__(self, graph: Any, *, run_type_prefix: str = "parent.") -> None:
        self._graph = graph
        self._run_type_prefix = run_type_prefix

    async def publish(self, message: OutboxMessage) -> None:
        if message.topic not in GRAPH_RESUME_TOPICS:
            raise ValueError("Parent Graph publisher received an unsupported topic")
        try:
            payload = WorkerResumePayload.model_validate_json(
                json.dumps(message.payload), strict=True
            )
        except ValidationError as exc:
            raise ValueError("Graph resume payload is invalid") from exc
        if payload.run_type is None or not payload.run_type.startswith(self._run_type_prefix):
            raise ValueError("Graph resume payload does not target the Parent Graph")
        config = {"configurable": {"thread_id": payload.thread_id}}
        snapshot = await self._graph.aget_state(config)
        values = snapshot.values
        if (
            payload.resume_event_id is not None
            and values.get("last_resume_event_id") == payload.resume_event_id
        ):
            return
        if values.get("terminal_status") is not None:
            raise ValueError("Parent Graph checkpoint is terminal for a different resume event")
        await self._graph.ainvoke(
            Command(resume=payload.model_dump(mode="json")),
            config,
        )


async def dispatch_once(
    store: OutboxStore,
    publisher: OutboxPublisher,
    *,
    owner: str,
    batch_size: int,
    lease_seconds: int,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    now = clock()
    messages = await store.claim_batch(
        owner=owner,
        now=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        batch_size=batch_size,
    )
    for message in messages:
        try:
            await publisher.publish(message)
        except Exception:
            await store.mark_failed(
                message.event_id,
                owner=owner,
                failed_at=clock(),
                error_code="OUTBOX_PUBLISH_FAILED",
                attempts=message.attempts,
            )
        else:
            await store.mark_published(message.event_id, owner=owner, published_at=clock())
    return len(messages)
