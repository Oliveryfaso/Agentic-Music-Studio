from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from motif_forge.application.piano_recovery import PianoRecoverySource, ReadPianoRecovery

NOW = datetime(2026, 10, 21, tzinfo=UTC)
P, B, R = UUID(int=1), UUID(int=2), UUID(int=3)


def source(n=1, **changes):
    value = dict(
        thread_id="piano-" + f"{n:032x}",
        branch_id=B,
        base_revision_id=R,
        created_at=NOW,
        preview_id=UUID(int=10 + n),
        candidate_content_hash="a" * 64,
        expires_at=NOW + timedelta(days=1),
    )
    return PianoRecoverySource(**(value | changes))


def state(item, phase="waiting_piano_approval", **changes):
    return (
        dict(
            operation="piano_preview",
            project_id=str(P),
            thread_id=item.thread_id,
            request_payload=dict(branch_id=str(B), base_revision_id=str(R)),
            phase=phase,
            piano_data=dict(
                project_id=str(P),
                branch_id=str(B),
                base_revision_id=str(R),
                preview_id=str(item.preview_id),
                candidate_content_hash=item.candidate_content_hash,
            ),
        )
        | changes
    )


class Store:
    def __init__(self, items):
        self.items = tuple(items)
        self.calls = []

    async def list_sources(self, **kw):
        self.calls.append(kw)
        return self.items


class Graph:
    def __init__(self, values):
        self.values = values
        self.calls = []

    async def aget_state(self, config):
        thread = config["configurable"]["thread_id"]
        self.calls.append(thread)
        value = self.values[thread]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(values=value, created_at=NOW.isoformat())


def reader(items, values=None):
    store = Store(items)
    graph = Graph(values or {})
    return ReadPianoRecovery(store, lambda: graph, clock=lambda: NOW), store, graph


@pytest.mark.asyncio
async def test_manual_multiple_stale_base_is_read_only_and_keeps_original_revision():
    older, latest = source(1, created_at=NOW - timedelta(hours=1)), source(2)
    read, store, graph = reader([latest, older], {x.thread_id: state(x) for x in [latest, older]})
    first = await read(P, B)
    second = await read(P, B)
    assert first == second
    assert first.recovery.status == "ready" and first.recovery.pending_count == 2
    assert first.recoverable.thread_id == latest.thread_id
    assert first.recoverable.base_revision_id == R  # no head rewrite/rebase
    assert first.recoverable.phase == "waiting_piano_approval"
    assert all(c == dict(project_id=P, branch_id=B, now=NOW, limit=11) for c in store.calls)
    assert len(graph.calls) == 4  # graph has no mutation methods


@pytest.mark.asyncio
async def test_true_empty_does_not_require_graph():
    read = ReadPianoRecovery(Store([]), lambda: None, clock=lambda: NOW)
    result = await read(P, B)
    assert result.recovery.status == "ready" and result.recovery.pending_count == 0
    assert result.recoverable is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "values_change",
    [
        {"operation": "export"},
        {"project_id": str(UUID(int=99))},
        {"thread_id": "piano-" + "f" * 32},
        {"request_payload": dict(branch_id=str(UUID(int=99)), base_revision_id=str(R))},
        {"request_payload": dict(branch_id=str(B), base_revision_id=str(UUID(int=99)))},
        {"piano_data": {}},
        {"piano_data": dict(preview_id=str(UUID(int=99)))},
        {"phase": "new_unknown_phase"},
    ],
)
async def test_bad_identity_or_phase_is_unavailable_not_empty(values_change):
    item = source()
    read, _, _ = reader([item], {item.thread_id: state(item, **values_change)})
    result = await read(P, B)
    assert result.recovery.status == "unavailable" and result.recovery.pending_count is None
    assert result.recoverable is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["completed", "rejected", "cancelled", "failed"])
async def test_terminal_graph_is_not_a_pending_candidate(phase):
    item = source()
    read, _, _ = reader([item], {item.thread_id: state(item, phase)})
    result = await read(P, B)
    assert result.recovery.status == "ready" and result.recovery.pending_count == 0


@pytest.mark.asyncio
async def test_expired_and_terminal_status_excluded_without_mutation():
    expired = source(1, expires_at=NOW)
    terminal = source(2)
    read, _, graph = reader(
        [expired, terminal], {terminal.thread_id: state(terminal, terminal_status="succeeded")}
    )
    result = await read(P, B)
    assert result.recovery.status == "ready" and result.recovery.pending_count == 0
    assert graph.calls == [terminal.thread_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["orphan", "empty", "exception", "no_graph", "wrong_source_branch"]
)
async def test_unreadable_evidence_does_not_claim_no_candidates(fault):
    item = source(thread_id=None) if fault == "orphan" else source()
    if fault == "wrong_source_branch":
        item = source(branch_id=UUID(int=99))
    read, _, _graph = reader(
        [item],
        {item.thread_id: RuntimeError("private internal detail") if fault == "exception" else {}},
    )
    if fault == "no_graph":
        read = ReadPianoRecovery(Store([item]), lambda: None, clock=lambda: NOW)
    result = await read(P, B)
    assert result.recovery.status == "unavailable" and result.recoverable is None
    assert "private" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_limit_fails_closed_before_graph_reads():
    read, _, graph = reader([source(n) for n in range(11)])
    result = await read(P, B)
    assert result.recovery.status == "limit_reached" and result.recovery.pending_count is None
    assert result.recoverable is None and not graph.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "planning"])
async def test_semantic_early_empty_checkpoint_falls_back_to_persisted_phase(phase):
    item = source(preview_id=None, candidate_content_hash=None, expires_at=None, early_phase=phase)
    read, _, _ = reader([item], {item.thread_id: {}})
    result = await read(P, B)
    assert result.recovery.status == "ready" and result.recoverable.phase == phase


@pytest.mark.asyncio
async def test_semantic_materialization_race_is_unavailable_until_business_record_visible():
    item = source(
        preview_id=None, candidate_content_hash=None, expires_at=None, early_phase="planning"
    )
    read, _, _ = reader([item], {item.thread_id: state(item)})
    result = await read(P, B)
    assert result.recovery.status == "unavailable"
