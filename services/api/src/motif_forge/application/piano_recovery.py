"""Bounded read-only discovery of piano auditions; exact-thread GET still owns HITL."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PianoRecoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PianoRecoverySource(PianoRecoveryModel):
    thread_id: str | None
    branch_id: UUID
    base_revision_id: UUID
    created_at: datetime
    preview_id: UUID | None = None
    candidate_content_hash: str | None = None
    expires_at: datetime | None = None
    early_phase: Literal["queued", "planning"] | None = None


class RecoverablePianoPreview(PianoRecoveryModel):
    thread_id: str
    branch_id: UUID
    base_revision_id: UUID
    phase: Literal["queued", "planning", "waiting_piano_worker", "waiting_piano_approval"]
    updated_at: datetime


class PianoRecoveryInfo(PianoRecoveryModel):
    status: Literal["ready", "unavailable", "limit_reached"] = "unavailable"
    pending_count: int | None = Field(default=None, ge=0, le=10)
    selection_rule: Literal["newest_created"] = "newest_created"
    reason_code: str | None = "PIANO_RECOVERY_UNAVAILABLE"


class PianoRecoveryDirectory(PianoRecoveryModel):
    recoverable: RecoverablePianoPreview | None = None
    recovery: PianoRecoveryInfo = Field(default_factory=PianoRecoveryInfo)


class PianoRecoveryStore(Protocol):
    async def list_sources(
        self, *, project_id: UUID, branch_id: UUID, now: datetime, limit: int
    ) -> tuple[PianoRecoverySource, ...]: ...


class ReadPianoRecovery:
    def __init__(
        self,
        store: PianoRecoveryStore,
        graph_getter: Callable[[], Any],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store, self._graph_getter, self._clock = store, graph_getter, clock

    async def __call__(self, project_id: UUID, branch_id: UUID) -> PianoRecoveryDirectory:
        try:
            # A read failure leaves the ordinary project workspace usable, but never
            # disguises unknown candidates as an empty directory. No exception text leaks.
            async with asyncio.timeout(3):
                return await self._read(project_id, branch_id)
        except Exception:
            return PianoRecoveryDirectory()

    async def _read(self, project_id: UUID, branch_id: UUID) -> PianoRecoveryDirectory:
        now = self._clock()
        sources = await self._store.list_sources(
            project_id=project_id,
            branch_id=branch_id,
            now=now,
            limit=11,
        )
        if len(sources) > 10:
            return PianoRecoveryDirectory(
                recovery=PianoRecoveryInfo(
                    status="limit_reached",
                    reason_code="PIANO_RECOVERY_LIMIT_REACHED",
                )
            )
        graph = self._graph_getter() if sources else None
        pending: list[tuple[datetime, RecoverablePianoPreview]] = []
        seen: set[str] = set()
        for item in sorted(sources, key=lambda s: (s.created_at, s.thread_id or ""), reverse=True):
            if item.expires_at is not None and item.expires_at <= now:
                continue
            thread = item.thread_id
            if item.branch_id != branch_id or thread is None or graph is None:
                return PianoRecoveryDirectory()
            if (
                not thread.startswith("piano-")
                or len(thread) != 38
                or any(c not in "0123456789abcdef" for c in thread[6:])
                or thread in seen
            ):
                return PianoRecoveryDirectory()
            seen.add(thread)
            snapshot = await graph.aget_state({"configurable": {"thread_id": thread}})
            value = snapshot.values
            phase: Any
            if not value and item.preview_id is None and item.early_phase is not None:
                phase = item.early_phase
            else:
                if (
                    not isinstance(value, dict)
                    or value.get("operation") != "piano_preview"
                    or value.get("project_id") != str(project_id)
                    or value.get("thread_id", thread) != thread
                ):
                    return PianoRecoveryDirectory()
                request = value.get("request_payload") or {}
                if request.get("branch_id") != str(branch_id) or request.get(
                    "base_revision_id"
                ) != str(item.base_revision_id):
                    return PianoRecoveryDirectory()
                phase = value.get("phase")
                if value.get("terminal_status") or phase in {
                    "completed",
                    "rejected",
                    "cancelled",
                    "failed",
                }:
                    continue
                prepared = value.get("piano_data")
                if item.preview_id is not None:
                    expected = dict(
                        project_id=str(project_id),
                        branch_id=str(branch_id),
                        base_revision_id=str(item.base_revision_id),
                        preview_id=str(item.preview_id),
                        candidate_content_hash=item.candidate_content_hash,
                    )
                    if not isinstance(prepared, dict) or any(
                        prepared.get(k) != v for k, v in expected.items()
                    ):
                        return PianoRecoveryDirectory()
                elif prepared or phase not in {"queued", "planning", "received"}:
                    # SQL/Graph materialization can race; retry a GET later, never
                    # invent a candidate identity from a half-published record.
                    return PianoRecoveryDirectory()
                if phase in {"received", "piano_prepared", "piano_step_collected"}:
                    phase = "planning"
                if phase not in {
                    "queued",
                    "planning",
                    "waiting_piano_worker",
                    "waiting_piano_approval",
                }:
                    return PianoRecoveryDirectory()
            updated = getattr(snapshot, "created_at", None)
            updated_at = datetime.fromisoformat(updated) if updated else item.created_at
            pending.append(
                (
                    item.created_at,
                    RecoverablePianoPreview(
                        thread_id=thread,
                        branch_id=branch_id,
                        base_revision_id=item.base_revision_id,
                        phase=phase,
                        updated_at=updated_at,
                    ),
                )
            )
        return PianoRecoveryDirectory(
            recoverable=pending[0][1] if pending else None,
            recovery=PianoRecoveryInfo(
                status="ready", pending_count=len(pending), reason_code=None
            ),
        )
