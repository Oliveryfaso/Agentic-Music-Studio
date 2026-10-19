"""P2.2: real PG result replay, one paid-slot reservation and exact range Undo."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from motif_forge.agent.planner import PersistentProviderBudgetLedger, ProviderBudgetExceeded
from motif_forge.application.ai_runs import ReadAIRun
from motif_forge.application.classical_import import ClassicalScoreRequest, CreateClassicalScore
from motif_forge.application.edit_runs import CreateEditAIRun, CreateEditAIRunRequest
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.piano_preview import PianoPreviewRequest, PianoPreviewWorkflow
from motif_forge.application.piano_semantic import PianoSemanticService
from motif_forge.application.previews import DecidePreview, DecidePreviewRequest, PreviewDecision
from motif_forge.application.undo import UndoCommittedRevision, UndoCommittedRevisionRequest
from motif_forge.domain.ai_runs import EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.piano_requests import PianoSemanticRequest
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.media_jobs import PostgresMediaJobUnitOfWork
from motif_forge.infrastructure.persistence.piano_plans import PostgresPianoPlanStore
from motif_forge.providers.deepseek import DeepSeekJsonClient
from motif_forge.providers.piano import DeepSeekPianoPlanner


def migrate(dsn):
    with patch.dict(os.environ, {"MOTIF_FORGE_POSTGRES_DSN": dsn}):
        command.upgrade(Config(Path(__file__).resolve().parents[4] / "alembic.ini"), "head")


@pytest.mark.asyncio
async def test_semantic_pg_plan_restart_replay_budget_range_and_undo(test_postgres_dsn):
    await asyncio.to_thread(migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai = PostgresAIRunUnitOfWork(sessions)
    store = PostgresPianoPlanStore(sessions)

    async def capability():
        return PianoCapability(available=True)

    submitted = []

    async def handler(req):
        submitted.append(1)
        body = json.loads(req.content)
        dynamic = json.loads(body["messages"][1]["content"])
        context = dynamic["context"]
        modify = context["mode"] == "modify"
        plan = {
            "schema_version": "accompaniment-plan.v1",
            "summary": "局部更轻更疏" if modify else "前半稀疏后半活跃",
            "bars": [
                {
                    "bar": i,
                    "chord": "G",
                    "grid": [0] if modify or i <= 8 else [0, 4, 8, 12],
                    "octave": 2,
                    "velocity": 36 if modify else 54,
                    "gate_steps": 3,
                }
                for i in range(context["start_bar"], context["end_bar"] + 1)
            ],
        }
        return httpx.Response(
            200,
            json={
                "id": "fake-" + str(len(submitted)),
                "model": "test-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"supported": True, "reason": "支持", "plan": plan}
                            )
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 200,
                    "total_tokens": 300,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 100,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:

        def planner(run):
            ledger = PersistentProviderBudgetLedger(
                ai, run_id=run.run_id, max_requests=1, max_total_tokens=12000
            )
            return DeepSeekPianoPlanner(
                DeepSeekJsonClient(
                    api_key="mock-only",
                    http_client=http,
                    max_attempts=1,
                    run_id=run.run_id,
                    budget_ledger=ledger,
                )
            )

        workflow = PianoPreviewWorkflow(
            projects,
            PostgresMediaJobUnitOfWork(sessions),
            capability,
            semantic=PianoSemanticService(ai, store, planner, projects=projects),
        )
        try:
            imported = await CreateClassicalScore(projects, capability)(
                ClassicalScoreRequest(), idempotency_key=uuid4().hex
            )
            semantic = PianoSemanticRequest(intent="前半稀疏后半活跃", mode="append")
            run = await CreateEditAIRun(ai)(
                CreateEditAIRunRequest(
                    project_id=imported.project_id,
                    branch_id=imported.branch_id,
                    base_revision_id=imported.revision_id,
                    thread_id="piano-" + uuid4().hex,
                    idempotency_key=uuid4().hex,
                    edit_request=EditRunRequest(
                        intent=semantic.intent, selection=Selection(), piano_request=semantic
                    ),
                    max_model_requests=1,
                    max_total_tokens=12000,
                )
            )
            request = PianoPreviewRequest(
                project_id=run.project_id,
                branch_id=run.branch_id,
                base_revision_id=run.base_revision_id,
                request_id=run.run_id,
                semantic=semantic,
            )
            first = await workflow.prepare(request, thread_id=run.thread_id)
            fresh = PianoPreviewWorkflow(
                projects,
                PostgresMediaJobUnitOfWork(sessions),
                capability,
                semantic=PianoSemanticService(
                    ai,
                    PostgresPianoPlanStore(sessions),
                    lambda r: (_ for _ in ()).throw(AssertionError("second paid client")),
                ),
            )
            assert await fresh.prepare(request, thread_id=run.thread_id) == first
            ledger = await ReadAIRun(ai)(run.run_id)
            assert (
                ledger.submitted_model_requests == 1
                and ledger.total_tokens == 300
                and len(submitted) == 1
            )
            async with projects() as tx:
                source = await tx.get_revision(imported.revision_id)
            with pytest.raises(ProviderBudgetExceeded):
                await planner(ledger).create(source.arrangement_ir, semantic)
            assert len(submitted) == 1
            # Persistence-only approval. Live UI separately checks rendered evidence.
            kept = await DecidePreview(projects)(
                DecidePreviewRequest(
                    preview_id=first.preview_id,
                    decision=PreviewDecision.APPROVE,
                    actor_id="human:pg-test",
                    approval_assertion="Persistence test approves this exact candidate.",
                    idempotency_key=uuid4().hex,
                )
            )
            async with projects() as tx:
                base = await tx.get_revision(kept.revision_id)
            target = base.arrangement_ir.tracks[1].track_id
            change = PianoSemanticRequest(
                intent="第9-12小节更疏更轻",
                mode="modify",
                target_track_id=target,
                start_bar=9,
                end_bar=12,
            )
            r2 = await CreateEditAIRun(ai)(
                CreateEditAIRunRequest(
                    project_id=run.project_id,
                    branch_id=run.branch_id,
                    base_revision_id=kept.revision_id,
                    thread_id="piano-" + uuid4().hex,
                    idempotency_key=uuid4().hex,
                    edit_request=EditRunRequest(
                        intent=change.intent,
                        selection=Selection(track_ids=(target,), start_tick=15360, end_tick=23040),
                        piano_request=change,
                    ),
                    max_model_requests=1,
                    max_total_tokens=12000,
                )
            )
            prepared = await workflow.prepare(
                PianoPreviewRequest(
                    project_id=r2.project_id,
                    branch_id=r2.branch_id,
                    base_revision_id=r2.base_revision_id,
                    request_id=r2.run_id,
                    semantic=change,
                ),
                thread_id=r2.thread_id,
            )
            changed = await DecidePreview(projects)(
                DecidePreviewRequest(
                    preview_id=prepared.preview_id,
                    decision=PreviewDecision.APPROVE,
                    actor_id="human:pg-test",
                    approval_assertion="Persistence test approves the exact selected bars.",
                    idempotency_key=uuid4().hex,
                )
            )
            undone = await UndoCommittedRevision(projects)(
                UndoCommittedRevisionRequest(
                    project_id=r2.project_id,
                    branch_id=r2.branch_id,
                    target_revision_id=changed.revision_id,
                    base_revision_id=changed.revision_id,
                    actor_id="human:pg-test",
                    idempotency_key=uuid4().hex,
                )
            )
            async with projects() as tx:
                restored = await tx.get_revision(undone.revision_id)
            assert (
                restored.content_hash == base.content_hash
                and restored.arrangement_ir == base.arrangement_ir
            )
            assert len(submitted) == 2 and await store.read(r2.run_id) is not None
        finally:
            await engine.dispose()
