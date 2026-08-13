"""Leased PostgreSQL Outbox delivery to the at-least-once media queue."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal, Protocol, cast
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from langgraph.types import Command
from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult

from motif_forge.agent.generate import (
    GenerateRequest,
    PlanApprovalDecision,
    initial_generate_state,
)
from motif_forge.domain.ai_runs import AIRun, AIRunStatus
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.media_jobs import WorkerResumePayload
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import OutboxEventRow

MEDIA_DISPATCH_TOPICS = frozenset({"media.job.dispatch.requested", "media.job.retry.requested"})
GRAPH_RESUME_TOPICS = frozenset({"graph.resume.requested"})
GRAPH_ACTION_TOPICS = frozenset(
    {"graph.start.requested", "graph.resume.requested", "graph.cancel.requested"}
)


class GraphActionPayload(DomainModel):
    schema_version: Literal["graph-action.v1"] = "graph-action.v1"
    action: Literal["start", "resume", "cancel"]
    run_id: UUID
    thread_id: str
    run_type: Literal["parent.generate.v1"]
    decision: PlanApprovalDecision | None = None

    def model_post_init(self, __context: object) -> None:
        del __context
        if (self.action == "resume") != (self.decision is not None):
            raise ValueError("resume requires one decision and other actions forbid it")


class AIRunLoader(Protocol):
    async def __call__(self, run_id: UUID) -> AIRun: ...


class PlanDecisionLoader(Protocol):
    async def __call__(self, run_id: UUID) -> PlanApprovalDecision: ...


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
        aggregate_type: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._topics = topics
        self._run_type_prefix = run_type_prefix
        self._aggregate_type = aggregate_type

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
            if self._aggregate_type is not None:
                conditions.append(OutboxEventRow.aggregate_type == self._aggregate_type)
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


class ParentGraphActionPublisher:
    """Dispatch strict generation actions from authoritative PostgreSQL state."""

    _ACTION_BY_TOPIC: ClassVar[dict[str, str]] = {
        "graph.start.requested": "start",
        "graph.resume.requested": "resume",
        "graph.cancel.requested": "cancel",
    }

    def __init__(
        self,
        graph: Any,
        *,
        load_run: AIRunLoader,
        load_decision: PlanDecisionLoader | None = None,
    ) -> None:
        self._graph = graph
        self._load_run = load_run
        self._load_decision = load_decision

    async def _graph_for(self, run: AIRun) -> Any:
        if callable(self._graph):
            candidate = self._graph(run)
            if hasattr(candidate, "__await__"):
                return await candidate
            return candidate
        return self._graph

    async def publish(self, message: OutboxMessage) -> None:
        expected_action = self._ACTION_BY_TOPIC.get(message.topic)
        if expected_action is None:
            raise ValueError("Parent Graph action publisher received an unsupported topic")
        try:
            payload = GraphActionPayload.model_validate_json(
                json.dumps(message.payload), strict=True
            )
        except ValidationError as exc:
            raise ValueError("Graph action payload is invalid") from exc
        if payload.action != expected_action:
            raise ValueError("Graph action topic does not match action")
        run = await self._load_run(payload.run_id)
        if run.thread_id != payload.thread_id or run.run_id != payload.run_id:
            raise ValueError("Graph action does not match authoritative AI Run")
        config = {"configurable": {"thread_id": run.thread_id}}
        graph = await self._graph_for(run)
        snapshot = await graph.aget_state(config)
        values = snapshot.values
        if payload.action == "start":
            if values:
                return
            if run.brief is None:
                raise ValueError("authoritative AI Run is missing its Brief")
            request = GenerateRequest.model_validate_json(
                json.dumps({
                    "run_id": run.run_id,
                    "project_id": run.project_id,
                    "branch_id": run.branch_id,
                    "base_revision_id": run.base_revision_id,
                    "brief": run.brief,
                    "seed": 0,
                    "expected_run_version": run.version,
                }, default=str),
                strict=True,
            )
            await graph.ainvoke(
                initial_generate_state(thread_id=run.thread_id, request=request), config
            )
            return
        if values.get("terminal_status") is not None:
            return
        if payload.action == "cancel":
            if run.status is not AIRunStatus.CANCELLED:
                raise ValueError("cancel action must be authoritative before Graph wake")
            if values.get("phase") == "waiting_plan_approval":
                await graph.ainvoke(Command(resume={"action": "cancel"}), config)
            return
        if values.get("phase") != "waiting_plan_approval":
            return
        decision = payload.decision
        if decision is None:
            if self._load_decision is None:
                raise ValueError("resume action is missing its authoritative decision")
            decision = await self._load_decision(run.run_id)
        await graph.ainvoke(Command(resume=decision.model_dump(mode="json")), config)


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
