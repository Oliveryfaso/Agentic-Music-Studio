"""Real PG, offline Provider: overlapping edits/Undo/ancestry; no rendered approval claim."""

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
from motif_forge.agent.planner import PersistentProviderBudgetLedger
from motif_forge.application.ai_runs import ReadAIRun
from motif_forge.application.classical_import import ClassicalScoreRequest, CreateClassicalScore
from motif_forge.application.edit_runs import CreateEditAIRun, CreateEditAIRunRequest
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.piano_preview import (
    PianoPreviewDecision,
    PianoPreviewRequest,
    PianoPreviewWorkflow,
)
from motif_forge.application.piano_semantic import PianoSemanticService
from motif_forge.application.previews import DecidePreview, DecidePreviewRequest, PreviewDecision
from motif_forge.application.undo import UndoCommittedRevision, UndoCommittedRevisionRequest
from motif_forge.domain.ai_runs import EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.piano_requests import PianoSemanticRequestV2
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
async def test_overlapping_edits_undo_reedit_and_stale_guards_use_exact_saved_ancestry(
    test_postgres_dsn,
):
    await asyncio.to_thread(migrate, test_postgres_dsn)
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai = PostgresAIRunUnitOfWork(sessions)
    store = PostgresPianoPlanStore(sessions)
    calls = []
    raw_plans = []

    async def capability():
        return PianoCapability(available=True)

    async def handler(req):
        body = json.loads(req.content)
        ctx = json.loads(body["messages"][1]["content"])["context"]
        calls.append(ctx)
        modify = ctx["mode"] == "modify"
        if modify:
            assert ctx["musical_fit"]["source_anchors"] == ctx["musical_fit"]["cadences"] == []
            assert set(ctx["fixed_register"]) == set(ctx["fixed_harmony"])
        plan = {
            "schema_version": "accompaniment-plan.v2",
            "beats_per_bar": 3,
            "summary": "offline synthetic multiround scope fixture",
            "bars": [
                {
                    "bar": i,
                    "chord": ctx["fixed_harmony"][str(i)] if modify else ("D" if i % 2 else "G"),
                    "octave": ctx["fixed_register"][str(i)] if modify else 2 + i % 2,
                    "grid": [0] if modify else [0, 4, 8],
                    "velocity": 36 + len(calls) if modify else 54,
                    "gate_steps": 2,
                }
                for i in range(ctx["start_bar"], ctx["end_bar"] + 1)
            ],
        }
        raw_plans.append(plan)
        return httpx.Response(
            200,
            json={
                "model": "offline-multiround",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"supported": True, "reason": "offline", "plan": plan}
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:

        def planner(run):
            return DeepSeekPianoPlanner(
                DeepSeekJsonClient(
                    api_key="mock-only",
                    http_client=http,
                    max_attempts=1,
                    run_id=run.run_id,
                    budget_ledger=PersistentProviderBudgetLedger(
                        ai, run_id=run.run_id, max_requests=1, max_total_tokens=12000
                    ),
                )
            )

        def workflow(factory=planner):
            return PianoPreviewWorkflow(
                projects,
                PostgresMediaJobUnitOfWork(sessions),
                capability,
                semantic=PianoSemanticService(ai, store, factory, projects=projects),
            )

        flow = workflow()

        async def revision(ident):
            async with projects() as tx:
                return await tx.get_revision(ident)

        async def keep(prepared):
            # PG persistence only; rendered HITL has a separate live boundary.
            return await DecidePreview(projects)(
                DecidePreviewRequest(
                    preview_id=prepared.preview_id,
                    decision=PreviewDecision.APPROVE,
                    actor_id="human:isolated-pg-test",
                    approval_assertion="Offline persistence fixture, not a listening acceptance.",
                    idempotency_key=uuid4().hex,
                )
            )

        requests = []
        try:
            imported = await CreateClassicalScore(projects, capability)(
                ClassicalScoreRequest(score_id="c01-minuet-g-a16.v1"), idempotency_key=uuid4().hex
            )
            original = await revision(imported.revision_id)

            async def prepare(base, start, end, mode):
                semantic = PianoSemanticRequestV2(
                    source_score_id="c01-minuet-g-a16.v1",
                    beats_per_bar=3,
                    mode=mode,
                    start_bar=start,
                    end_bar=end,
                    target_track_id=base.arrangement_ir.tracks[1].track_id
                    if mode == "modify"
                    else None,
                    intent="保留原和声与音区,更轻更稀疏"
                    if mode == "modify"
                    else "offline append fixture",
                )
                creation = CreateEditAIRunRequest(
                    project_id=imported.project_id,
                    branch_id=imported.branch_id,
                    base_revision_id=base.revision_id,
                    thread_id="daily-" + uuid4().hex,
                    idempotency_key=uuid4().hex,
                    edit_request=EditRunRequest(
                        intent=semantic.intent,
                        selection=(
                            Selection(
                                track_ids=(semantic.target_track_id,),
                                start_tick=(start - 1) * 1440,
                                end_tick=end * 1440,
                            )
                            if mode == "modify"
                            else Selection()
                        ),
                        piano_request=semantic,
                    ),
                    max_model_requests=1,
                    max_total_tokens=12000,
                )
                run = await CreateEditAIRun(ai)(creation)
                same = await CreateEditAIRun(ai)(creation)
                assert same.run_id == run.run_id
                request = PianoPreviewRequest(
                    project_id=run.project_id,
                    branch_id=run.branch_id,
                    base_revision_id=run.base_revision_id,
                    request_id=run.run_id,
                    semantic=semantic,
                )
                requests.append((request, run.thread_id))
                before = len(calls)
                prepared = await flow.prepare(request, thread_id=run.thread_id)
                assert len(calls) == before + 1

                def never(_):
                    raise AssertionError("Saved replay must not construct a Provider")

                assert await workflow(never).prepare(request, thread_id=run.thread_id) == prepared
                assert len(calls) == before + 1
                record = await store.read(run.run_id)
                assert record["plan"] == raw_plans[-1]
                usage = await ReadAIRun(ai)(run.run_id)
                assert usage.submitted_model_requests == 1 and usage.total_tokens == 300
                return prepared

            full = await prepare(original, 1, 16, "append")
            v1 = await revision((await keep(full)).revision_id)
            first = await prepare(v1, 1, 4, "modify")
            v2 = await revision((await keep(first)).revision_id)
            overlap = await prepare(v2, 3, 6, "modify")
            with pytest.raises(ApplicationError) as bad_hash:
                await flow.decide(
                    overlap,
                    PianoPreviewDecision(
                        action="approve",
                        expected_candidate_content_hash="0" * 64,
                        approval_assertion="Wrong hash must never commit.",
                    ),
                    None,
                )
            assert bad_hash.value.code == "PIANO_CANDIDATE_HASH_MISMATCH" and len(calls) == 3
            v3 = await revision((await keep(overlap)).revision_id)
            for before, after, start, end in [(v1, v2, 1, 4), (v2, v3, 3, 6)]:
                a, b = (start - 1) * 1440, end * 1440

                def outside(v, left=a, right=b):
                    return tuple(
                        n
                        for n in v.arrangement_ir.tracks[1].clips[0].notes
                        if not left <= n.start_tick < right
                    )

                assert outside(before) == outside(after)
                assert after.arrangement_ir.tracks[0] == original.arrangement_ir.tracks[0]
            undone = await UndoCommittedRevision(projects)(
                UndoCommittedRevisionRequest(
                    project_id=imported.project_id,
                    branch_id=imported.branch_id,
                    target_revision_id=v3.revision_id,
                    base_revision_id=v3.revision_id,
                    actor_id="human:isolated-pg-test",
                    idempotency_key=uuid4().hex,
                )
            )
            restored = await revision(undone.revision_id)
            assert (
                restored.content_hash == v2.content_hash
                and restored.arrangement_ir == v2.arrangement_ir
            )
            tail = await prepare(restored, 13, 16, "modify")
            v4 = await revision((await keep(tail)).revision_id)
            assert calls[-1]["fixed_register"] == {str(i): 2 + i % 2 for i in range(13, 17)}
            assert v4.arrangement_ir.tracks[0] == original.arrangement_ir.tracks[0]
            old_request, old_thread = requests[1]
            with pytest.raises(ApplicationError) as stale:
                await flow.prepare(old_request, thread_id=old_thread)
            assert stale.value.code == "REVISION_CONFLICT" and len(calls) == 4
        finally:
            await engine.dispose()
