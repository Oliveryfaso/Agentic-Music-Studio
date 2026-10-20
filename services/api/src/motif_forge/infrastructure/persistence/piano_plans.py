"""Immutable replay boundary for validated semantic piano plans, never raw responses."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from motif_forge.application.errors import ApplicationError
from motif_forge.domain.piano_record import validate_v2_record
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import PianoAccompanimentPlanRow
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

_FORBIDDEN_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "response",
        "raw_response",
        "reasoning",
        "reasoning_content",
        "api_key",
        "secret",
        "authorization",
        "password",
        "access_token",
        "refresh_token",
    }
)


def _copy_record(value: dict[str, Any]) -> dict[str, Any]:
    def validate(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str) or key.casefold() in _FORBIDDEN_KEYS:
                    raise ValueError("raw prompts, responses, reasoning and secrets are forbidden")
                validate(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                validate(nested)

    try:
        if value.get("schema_version") not in ("piano-plan-record.v1", "piano-plan-record.v2"):
            raise ValueError("unsupported piano plan record version")
        validate(value)
        if value["schema_version"] == "piano-plan-record.v2":
            validate_v2_record(value)
        return json.loads(json.dumps(value, allow_nan=False))  # type: ignore[no-any-return]
    except (KeyError, TypeError, ValueError) as exc:
        raise ApplicationError(
            "PIANO_PLAN_RECORD_INVALID", "Only a validated, safe piano plan record may be stored."
        ) from exc


class PostgresPianoPlanStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sessions = session_factory

    async def read(self, run_id: UUID) -> dict[str, Any] | None:
        async with self._sessions() as session:
            payload = (
                await session.execute(
                    select(PianoAccompanimentPlanRow.payload).where(
                        PianoAccompanimentPlanRow.run_id == run_id
                    )
                )
            ).scalar_one_or_none()
        return _copy_record(payload) if payload is not None else None

    async def save(self, run_id: UUID, record: dict[str, Any]) -> dict[str, Any]:
        payload = _copy_record(record)
        async with self._sessions() as session, session.begin():
            # The PK serializes concurrent inserts; a losing writer reads the winner,
            # compares exact content, and never overwrites an already paid result.
            await session.execute(
                insert(PianoAccompanimentPlanRow)
                .values(run_id=run_id, schema_version=payload["schema_version"], payload=payload)
                .on_conflict_do_nothing(index_elements=[PianoAccompanimentPlanRow.run_id])
            )
            stored = (
                await session.execute(
                    select(PianoAccompanimentPlanRow.payload).where(
                        PianoAccompanimentPlanRow.run_id == run_id
                    )
                )
            ).scalar_one()
            if stored != payload:
                raise ApplicationError(
                    "PIANO_PLAN_RECORD_CONFLICT", "This AI Run already owns another piano plan."
                )
            return _copy_record(stored)
