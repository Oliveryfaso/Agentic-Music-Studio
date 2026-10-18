import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from motif_forge.application.rendering import build_canonical_render_payload
from motif_forge.config import Settings
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.media_jobs import MediaJobType
from motif_forge.domain.revisions import create_root_state
from motif_forge.worker.execution import _run_artifact_storage_gate


@pytest.mark.asyncio
async def test_capacity_rejection_returns_worker_failure_label_without_storage_or_render():
    base = create_root_state(UUID(int=50), created_by="test").revision
    base = base.model_copy(
        update={"arrangement_ir": build_s1_composition(UUID(int=50), seed=0).arrangement}
    )
    base = base.model_copy(update={"content_hash": arrangement_content_hash(base.arrangement_ir)})
    payload = build_canonical_render_payload(base, seed=42)
    graph = payload.audio_graph.copy()
    graph["durationSeconds"] = 301
    payload = payload.model_copy(
        update={
            "audio_graph": graph,
            "audio_graph_hash": hashlib.sha256(
                json.dumps(
                    graph, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        }
    )
    job = SimpleNamespace(
        job_type=MediaJobType.RENDER_CANONICAL,
        input_payload=payload.model_dump(mode="json"),
        project_id=payload.project_id,
        job_id=UUID(int=51),
    )
    result = await _run_artifact_storage_gate(
        job, Settings.for_test(), SimpleNamespace(session_factory=None)
    )
    assert result == "RENDER_CAPACITY_INVALID"


@pytest.mark.asyncio
async def test_storage_gate_reserves_two_derived_pcm_copies_not_legacy_two_gib(monkeypatch):
    from motif_forge.domain.storage import StorageRoute
    from motif_forge.worker import execution

    base = create_root_state(UUID(int=52), created_by="test").revision
    arrangement = build_s1_composition(base.project_id, seed=0).arrangement
    base = base.model_copy(
        update={
            "arrangement_ir": arrangement,
            "content_hash": arrangement_content_hash(arrangement),
        }
    )
    payload = build_canonical_render_payload(base, seed=42)
    graph = payload.audio_graph.copy()
    graph["durationSeconds"] = 300
    payload = payload.model_copy(
        update={
            "audio_graph": graph,
            "audio_graph_hash": hashlib.sha256(
                json.dumps(
                    graph, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "maximum_output_bytes": 2_147_483_648,
        }
    )
    job = SimpleNamespace(
        job_type=MediaJobType.RENDER_CANONICAL,
        input_payload=payload.model_dump(mode="json"),
        project_id=payload.project_id,
        job_id=UUID(int=53),
        attempts=1,
    )
    estimates = []

    class Gate:
        def __init__(self, **kwargs):
            pass

        async def __call__(self, **kwargs):
            estimates.append(kwargs)
            return SimpleNamespace(route=StorageRoute.PROCEED)

    monkeypatch.setattr(execution, "RunStoragePressureGate", Gate)
    assert (
        await _run_artifact_storage_gate(
            job, Settings.for_test(), SimpleNamespace(session_factory=None)
        )
        is None
    )
    assert estimates[0]["estimated_artifact_bytes"] == 86_400_044
    assert estimates[0]["estimated_temp_bytes"] == 86_400_044
