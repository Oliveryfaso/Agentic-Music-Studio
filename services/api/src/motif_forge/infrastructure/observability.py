"""PostgreSQL Trace/Span and Usage Ledger recorder."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import TraceRow, TraceSpanRow, UsageLedgerRow
from motif_forge.observability.models import ModelCallRecord


class PostgresTelemetryRecorder:
    """Persist model telemetry idempotently by provider operation id."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def record_model_call(self, record: ModelCallRecord) -> None:
        trace_id = uuid4()
        span_id = uuid4()
        latency_ms = max(0, int((record.ended_at - record.started_at).total_seconds() * 1000))
        response = record.response
        async with self._session_factory.begin() as session:
            trace_statement = (
                insert(TraceRow)
                .values(
                    id=trace_id,
                    run_id=record.run_id,
                    thread_id=record.thread_id,
                    trace_name="composition-plan",
                    status=record.status,
                    started_at=record.started_at,
                    updated_at=record.ended_at,
                )
                .on_conflict_do_update(
                    index_elements=[TraceRow.run_id],
                    set_={"status": record.status, "updated_at": record.ended_at},
                )
                .returning(TraceRow.id)
            )
            persisted_trace_id = (await session.execute(trace_statement)).scalar_one()
            span_statement = (
                insert(TraceSpanRow)
                .values(
                    id=span_id,
                    trace_id=persisted_trace_id,
                    operation_id=record.operation_id,
                    run_id=record.run_id,
                    node=record.node,
                    span_kind="model_call",
                    status=record.status,
                    provider=record.provider,
                    model=record.model,
                    prompt_version=record.prompt_version,
                    schema_version=record.schema_version,
                    thinking_mode=record.thinking_mode,
                    safe_summary={"structured_output_valid": record.status == "succeeded"},
                    error_code=record.error_code,
                    started_at=record.started_at,
                    ended_at=record.ended_at,
                    latency_ms=latency_ms,
                )
                .on_conflict_do_nothing(index_elements=[TraceSpanRow.operation_id])
                .returning(TraceSpanRow.id)
            )
            persisted_span_id = (await session.execute(span_statement)).scalar_one_or_none()
            if persisted_span_id is None or response is None:
                return
            usage = response.usage
            await session.execute(
                insert(UsageLedgerRow)
                .values(
                    operation_id=record.operation_id,
                    trace_span_id=persisted_span_id,
                    run_id=record.run_id,
                    node=record.node,
                    provider=record.provider,
                    model=record.model,
                    model_calls=response.model_calls,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    prompt_cache_hit_tokens=usage.prompt_cache_hit_tokens,
                    prompt_cache_miss_tokens=usage.prompt_cache_miss_tokens,
                    reasoning_tokens=usage.reasoning_tokens,
                    estimated_cost_microusd=None,
                    cost_status="unknown",
                    pricing_version=None,
                    created_at=record.ended_at,
                )
                .on_conflict_do_nothing(index_elements=[UsageLedgerRow.operation_id])
            )
