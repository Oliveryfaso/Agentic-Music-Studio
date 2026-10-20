"""Saved real Q4 counterexample, replayed offline through production service."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from motif_forge.agent.planner import PlannerError
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_preview import PianoPreviewRequest
from motif_forge.domain.commands import Selection, apply_commands
from motif_forge.domain.ir import read_arrangement_json
from motif_forge.domain.piano_register import register_preservation_requested
from motif_forge.domain.piano_requests import read_piano_request
from motif_forge.providers.deepseek import DeepSeekJsonClient
from motif_forge.providers.piano import DeepSeekPianoPlanner

FIXTURE = Path(__file__).parents[2] / "fixtures/piano/q4-register-real-20261020.json"
REGISTER = {9: 2, 10: 3, 11: 2, 12: 3}


async def replay(monkeypatch, *, valid=False, cached=False, source="saved", intent=None):
    import motif_forge.application.piano_semantic as service

    data = json.loads(FIXTURE.read_text())
    base = read_arrangement_json(json.dumps(data["base_ir"]))
    semantic = read_piano_request(json.dumps(data["q4_record"]["request"]))
    if intent is not None:
        semantic = semantic.model_copy(update={"intent": intent})
    run = SimpleNamespace(
        project_id=base.project_id,
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        run_id=uuid4(),
        edit_request={
            "intent": semantic.intent,
            "selection": Selection(
                track_ids=(semantic.target_track_id,),
                start_tick=(semantic.start_bar - 1) * semantic.bar_ticks,
                end_tick=semantic.end_bar * semantic.bar_ticks,
            ).model_dump(mode="json"),
            "piano_request": semantic.model_dump(mode="json"),
        },
    )
    previous_run, ancestor = UUID(data["q1_run_id"]), uuid4()
    prior = copy.deepcopy(data["q1_record"])
    if source == "tampered":
        prior["plan"]["bars"][9]["octave"] = 2

    async def load(_):
        return run

    monkeypatch.setattr(service, "ReadAIRunByThreadId", lambda _: load)

    class Tx:
        reads = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get_revision(self, ident):
            self.reads += 1
            if source == "cycle":
                return SimpleNamespace(
                    revision_id=ident,
                    project_id=base.project_id,
                    source_run_id=None,
                    parent_revision_id=ident,
                    arrangement_ir=base,
                )
            if ident not in (run.base_revision_id, ancestor):
                return None
            undo = source == "undo" and ident != ancestor
            return SimpleNamespace(
                revision_id=ident,
                project_id=base.project_id,
                source_run_id=None if undo else previous_run,
                parent_revision_id=ancestor if undo else None,
                arrangement_ir=base,
            )

        async def list_revision_commands(self, _):
            return ()

    raw = copy.deepcopy(data["q4_record"])
    raw["request"] = semantic.model_dump(mode="json")
    if valid:
        for bar in raw["plan"]["bars"]:
            bar["octave"] = REGISTER[bar["bar"]]
    if intent == "仅提高第9到12小节伴奏音区,保留原和声":
        for bar in raw["plan"]["bars"]:
            bar["octave"] = 3

    class Store:
        saves = 0
        saved = None

        async def read(self, ident):
            if ident == previous_run:
                return copy.deepcopy(prior)
            return copy.deepcopy(raw) if cached else None

        async def save(self, ident, record):
            self.saves += 1
            self.saved = copy.deepcopy(record)
            return copy.deepcopy(record)

    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "offline-q4-counterexample",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "supported": True,
                                    "reason": "offline fixture, no real call",
                                    "plan": raw["plan"],
                                }
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            },
        )

    store, tx = Store(), Tx()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:

        def planner(_):
            if cached or source in {"tampered", "cycle"}:
                raise AssertionError("unverified/cached input must not build a paid client")
            return DeepSeekPianoPlanner(
                DeepSeekJsonClient(api_key="mock-only", http_client=http, max_attempts=1)
            )

        try:
            result = await service.PianoSemanticService(
                None, store, planner, projects=lambda: tx
            ).prepare(
                PianoPreviewRequest(
                    project_id=run.project_id,
                    branch_id=run.branch_id,
                    base_revision_id=run.base_revision_id,
                    request_id=run.run_id,
                    semantic=semantic,
                ),
                base,
                thread_id="offline-real-q4",
            )
        except (ApplicationError, PlannerError) as error:
            return error, store, requests, base, raw, tx
    return result, store, requests, base, raw, tx


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_real_q4_register_violation_rejected_without_saving_or_repair(monkeypatch, cached):
    before_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    error, store, requests, _, _, _ = await replay(monkeypatch, cached=cached)
    assert error.code == "PIANO_REGISTER_CHANGED"
    assert store.saves == 0
    assert len(requests) == (0 if cached else 1)
    if requests:
        context = json.loads(requests[0]["messages"][1]["content"])["context"]
        assert context["fixed_register"] == {str(k): v for k, v in REGISTER.items()}
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == before_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("cached,source", [(False, "saved"), (True, "saved"), (False, "undo")])
async def test_compliant_result_preserves_plan_and_protected_notes(monkeypatch, cached, source):
    result, store, requests, base, raw, _ = await replay(
        monkeypatch, valid=True, cached=cached, source=source
    )
    commands, record, _ = result
    assert record["plan"] == raw["plan"]  # no octave postprocessing
    if not cached:
        assert store.saves == 1 and store.saved["register_policy"] == "piano-register-preserved.v1"
    assert len(requests) == (0 if cached else 1)
    candidate = apply_commands(base, commands)
    assert candidate.tracks[0] == base.tracks[0]
    first, last = 8 * 1440, 12 * 1440

    def outside(ir):
        return tuple(
            n for n in ir.tracks[1].clips[0].notes if n.start_tick < first or n.start_tick >= last
        )

    assert outside(candidate) == outside(base)


@pytest.mark.asyncio
async def test_unproven_octave_metadata_refused_before_paid_client(monkeypatch):
    error, store, requests, *_ = await replay(monkeypatch, source="tampered")
    assert error.code == "PIANO_REGISTER_UNVERIFIED"
    assert store.saves == 0 and requests == []


@pytest.mark.asyncio
async def test_ancestry_cycle_has_finite_cost_and_no_paid_client(monkeypatch):
    error, store, requests, _, _, tx = await replay(monkeypatch, source="cycle")
    assert error.code == "PIANO_HARMONY_UNVERIFIED"
    assert tx.reads == 64 and store.saves == 0 and requests == []


@pytest.mark.asyncio
async def test_explicit_register_change_remains_supported(monkeypatch):
    result, _, requests, _, raw, _ = await replay(
        monkeypatch, intent="仅提高第9到12小节伴奏音区,保留原和声"
    )
    assert result[1]["plan"] == raw["plan"]
    assert "fixed_register" not in json.loads(requests[0]["messages"][1]["content"])["context"]


@pytest.mark.parametrize(
    "intent",
    [
        "保留原和弦与音区,更轻更稀疏",
        "音区不变,降低力度",
        "不改变原音区",
        "Keep register and lower velocity",
        "preserve register, change density",
    ],
)
def test_explicit_keep_register_phrases(intent):
    assert register_preservation_requested(intent)


@pytest.mark.parametrize(
    "intent", ["提高伴奏音区,保留原和声", "lower register and velocity", "更轻更稀疏"]
)
def test_no_implicit_register_lock(intent):
    assert not register_preservation_requested(intent)


@pytest.mark.parametrize(
    "intent",
    [
        "保留音区,但降低一个八度",
        "keep register; raise octave",
        "不要保持音区",
        "do not keep register",
    ],
)
def test_conflicting_register_request_fails_closed(intent):
    with pytest.raises(ValueError, match="PIANO_REGISTER_INTENT_UNSUPPORTED"):
        register_preservation_requested(intent)
