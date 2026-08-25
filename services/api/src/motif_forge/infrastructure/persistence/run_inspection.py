"""PostgreSQL Run Inspector read projection."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from motif_forge.application.run_inspection import (
    DecisionSummary,
    InspectionArtifact,
    InspectionEvent,
    InspectionJob,
    InspectionRunSummary,
    RecoverySummary,
    RunInspectionFacts,
    RunUsageSummary,
    RunVersionSummary,
    safe_event_summary,
)
from motif_forge.infrastructure.persistence.database import SessionFactory
from motif_forge.infrastructure.persistence.tables import (
    AIRunApprovalRow,
    AIRunEditDecisionRow,
    AIRunEventRow,
    AIRunRow,
    AudioArtifactRow,
    ExportBundleArtifactRow,
    MediaJobRow,
)

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "rejected"}


class PostgresRunInspectionStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_run_inspection(self, run_id: UUID) -> RunInspectionFacts | None:
        async with self._session_factory() as session:
            run = (
                await session.execute(select(AIRunRow).where(AIRunRow.id == run_id))
            ).scalar_one_or_none()
            if run is None:
                return None
            raw_events = tuple(
                (
                    await session.execute(
                        select(AIRunEventRow)
                        .where(AIRunEventRow.run_id == run_id)
                        .order_by(AIRunEventRow.sequence.desc())
                        .limit(201)
                    )
                ).scalars()
            )
            approval = (
                await session.execute(
                    select(AIRunApprovalRow).where(AIRunApprovalRow.run_id == run_id)
                )
            ).scalar_one_or_none()
            edit_decision = (
                await session.execute(
                    select(AIRunEditDecisionRow).where(AIRunEditDecisionRow.run_id == run_id)
                )
            ).scalar_one_or_none()
            revision_id = run.materialized_revision_id
            jobs: tuple[MediaJobRow, ...] = ()
            artifacts: tuple[AudioArtifactRow, ...] = ()
            bundle = None
            if revision_id is not None:
                project_jobs = tuple(
                    (
                        await session.execute(
                            select(MediaJobRow)
                            .where(MediaJobRow.project_id == run.project_id)
                            .order_by(MediaJobRow.created_at, MediaJobRow.id)
                        )
                    ).scalars()
                )
                jobs = tuple(
                    item
                    for item in project_jobs
                    if item.input_payload.get("revision_id") == str(revision_id)
                )
                artifacts = tuple(
                    (
                        await session.execute(
                            select(AudioArtifactRow)
                            .where(
                                AudioArtifactRow.project_id == run.project_id,
                                AudioArtifactRow.revision_id == revision_id,
                            )
                            .order_by(AudioArtifactRow.created_at, AudioArtifactRow.id)
                        )
                    ).scalars()
                )
                bundle = (
                    await session.execute(
                        select(ExportBundleArtifactRow).where(
                            ExportBundleArtifactRow.project_id == run.project_id,
                            ExportBundleArtifactRow.revision_id == revision_id,
                        )
                    )
                ).scalar_one_or_none()

        events = tuple(reversed(raw_events[:200]))
        timeline = tuple(
            InspectionEvent(
                sequence=item.sequence, event_type=item.event_type, phase=item.phase,
                created_at=item.created_at,
                summary=safe_event_summary(item.event_type, item.payload),
            )
            for item in events
        )
        decisions: list[DecisionSummary] = []
        if approval is not None:
            decisions.append(DecisionSummary(
                kind="plan", decision=approval.decision, actor_id=approval.actor_id,
                decided_at=approval.decided_at,
            ))
        if edit_decision is not None:
            decisions.append(DecisionSummary(
                kind="edit", decision=edit_decision.action, actor_id=edit_decision.actor_id,
                decided_at=edit_decision.created_at,
            ))
        decisions.sort(key=lambda item: item.decided_at)
        error_code = next(
            (
                value
                for item in reversed(timeline)
                if isinstance((value := item.summary.get("error_code")), str)
            ),
            None,
        )
        event_names = tuple(item.event_type.lower() for item in timeline)
        return RunInspectionFacts(
            run=InspectionRunSummary(
                run_id=run.id, project_id=run.project_id, run_type=run.run_type,
                status=run.status, version=run.version, revision_id=revision_id,
                bundle_id=bundle.id if bundle is not None else None, error_code=error_code,
            ),
            versions=RunVersionSummary(
                graph_topology_version=run.graph_topology_version,
                state_schema_version=run.state_schema_version,
            ),
            usage=RunUsageSummary(
                submitted_model_requests=run.submitted_model_requests,
                max_model_requests=run.max_model_requests,
                max_total_tokens=run.max_total_tokens,
                prompt_tokens=run.prompt_tokens, completion_tokens=run.completion_tokens,
                total_tokens=run.total_tokens, usage_status=run.model_usage_status,
                cost_status=run.cost_status, cost_amount_microusd=run.cost_microusd,
            ),
            timeline=timeline, timeline_truncated=len(raw_events) > 200,
            decisions=tuple(decisions),
            jobs=tuple(InspectionJob(
                job_id=item.id, job_type=item.job_type, status=item.status,
                attempts=item.attempts, error_code=item.error_code,
            ) for item in jobs),
            artifacts=tuple(InspectionArtifact(
                artifact_id=item.id, source_job_id=item.source_job_id,
                quality_profile=item.quality_profile, availability=item.availability,
                byte_size=item.byte_size,
            ) for item in artifacts if item.source_job_id is not None),
            recovery=RecoverySummary(
                resume_events=sum("resum" in item for item in event_names),
                replay_events=sum("replay" in item or "dedup" in item for item in event_names),
                retry_events=sum("retry" in item for item in event_names),
                cancel_events=sum("cancel" in item for item in event_names),
                terminal_outcome=run.status if run.status in TERMINAL_STATUSES else None,
            ),
        )
