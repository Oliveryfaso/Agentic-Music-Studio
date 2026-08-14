from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.schemas import CompositionBrief
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V2,
    approval_assertion_hash,
    composition_plan_content_hash,
)

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_s2_live_deepseek_smoke import (  # noqa: E402
    LIVE_BRIEF,
    acceptance_keys,
    build_safe_summary,
    load_live_guard,
    validate_persisted_approval,
    validate_persisted_plan,
    validate_projection_budget,
)


def _live_env() -> dict[str, str]:
    return {
        "MOTIF_FORGE_S2_LIVE": "1",
        "DEEPSEEK_API_KEY": "test-key-placeholder-not-real",
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
        "MOTIF_FORGE_S2_APPROVAL_ACTOR": "live-contract-reviewer",
        "MOTIF_FORGE_S2_APPROVAL_ASSERTION": (
            "I reviewed and approve this exact live S2 composition plan."
        ),
    }


@pytest.mark.parametrize(
    ("removed", "message"),
    (
        ("MOTIF_FORGE_S2_LIVE", "explicit opt-in"),
        ("DEEPSEEK_API_KEY", "provider key"),
        ("MOTIF_FORGE_S2_APPROVAL_ACTOR", "approval actor"),
        ("MOTIF_FORGE_S2_APPROVAL_ASSERTION", "approval assertion"),
    ),
)
def test_live_guard_fails_before_http_without_required_authority(
    removed: str, message: str
) -> None:
    env = _live_env()
    env.pop(removed)

    with pytest.raises(RuntimeError, match=message):
        load_live_guard(env)


def test_live_guard_refuses_any_model_other_than_reviewed_flash_model() -> None:
    env = _live_env()
    env["DEEPSEEK_MODEL"] = "deepseek-chat"

    with pytest.raises(RuntimeError, match="deepseek-v4-flash"):
        load_live_guard(env)


def test_live_guard_and_projection_enforce_request_and_token_budgets() -> None:
    guard = load_live_guard(_live_env())

    assert guard.model == "deepseek-v4-flash"
    assert guard.max_model_requests == 3
    assert guard.max_total_tokens == 12_000
    validate_projection_budget(
        {
            "max_model_requests": 3,
            "submitted_model_requests": 3,
            "total_tokens": 12_000,
            "model_usage_status": "known",
        },
        guard,
    )
    with pytest.raises(RuntimeError, match="request budget"):
        validate_projection_budget(
            {
                "max_model_requests": 3,
                "submitted_model_requests": 4,
                "total_tokens": 100,
                "model_usage_status": "known",
            },
            guard,
        )
    with pytest.raises(RuntimeError, match="token budget"):
        validate_projection_budget(
            {
                "max_model_requests": 3,
                "submitted_model_requests": 1,
                "total_tokens": 12_001,
                "model_usage_status": "known",
            },
            guard,
        )
    with pytest.raises(RuntimeError, match="known model usage"):
        validate_projection_budget(
            {
                "max_model_requests": 3,
                "submitted_model_requests": 1,
                "total_tokens": None,
                "model_usage_status": "unknown",
            },
            guard,
        )


def test_live_acceptance_identity_is_fixed_across_process_like_calls() -> None:
    first = acceptance_keys()
    second = acceptance_keys()

    assert first == second
    assert first.project == "s2-live-deepseek-acceptance-v1-project"
    assert first.run == "s2-live-deepseek-acceptance-v1-run"
    assert first.resume == "s2-live-deepseek-acceptance-v1-resume"


def test_live_plan_requires_strict_schema_and_recomputed_v2_hash() -> None:
    brief = CompositionBrief.model_validate_json(json.dumps(LIVE_BRIEF), strict=True)
    plan = build_fallback_plan(brief)
    plan_hash = composition_plan_content_hash(plan, hash_version=PLAN_HASH_VERSION_V2)
    row = {
        "plan": plan.model_dump(mode="json"),
        "content_hash": plan_hash,
        "hash_version": PLAN_HASH_VERSION_V2,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "fallback_reason": None,
    }

    assert validate_persisted_plan(
        row, pending_hash=plan_hash, expected_model="deepseek-v4-flash"
    ) == plan

    coerced = dict(row)
    coerced["plan"] = {**row["plan"], "bpm": "72"}
    with pytest.raises(ValueError):
        validate_persisted_plan(
            coerced, pending_hash=plan_hash, expected_model="deepseek-v4-flash"
        )

    wrong_hash = dict(row, content_hash="0" * 64)
    with pytest.raises(RuntimeError, match="content hash"):
        validate_persisted_plan(
            wrong_hash, pending_hash=plan_hash, expected_model="deepseek-v4-flash"
        )


def test_live_approval_is_independently_bound_to_reviewed_facts() -> None:
    guard = load_live_guard(_live_env())
    plan_hash = "a" * 64
    interrupt_ref = "persisted-interrupt"
    row = {
        "assertion_hash": approval_assertion_hash(guard.assertion),
        "decision": "approve",
        "actor_id": guard.actor,
        "expected_plan_content_hash": plan_hash,
        "interrupt_ref": interrupt_ref,
    }

    validate_persisted_approval(
        row,
        guard=guard,
        plan_hash=plan_hash,
        expected_interrupt_ref=interrupt_ref,
    )
    with pytest.raises(RuntimeError, match="approval evidence"):
        validate_persisted_approval(
            dict(row, actor_id="someone-else"),
            guard=guard,
            plan_hash=plan_hash,
            expected_interrupt_ref=interrupt_ref,
        )


def test_safe_summary_is_bounded_and_cannot_include_sensitive_provider_fields() -> None:
    summary = build_safe_summary(
        run_id=uuid4(),
        thread_id="generate-live-contract",
        revision_id=uuid4(),
        bundle_id=uuid4(),
        media_run_id=uuid4(),
        job_count=7,
        audio_artifact_count=6,
        checksums={str(uuid4()): "a" * 64 for _ in range(6)},
        provider="deepseek",
        model="deepseek-v4-flash",
        model_calls=1,
        total_tokens=321,
        latency_ms=1234,
        cost_status="unknown",
        fallback_used=False,
    )
    encoded = json.dumps(summary, sort_keys=True)

    assert len(encoded.encode()) < 4096
    assert set(summary) == {
        "run_id",
        "thread_id",
        "revision_id",
        "bundle_id",
        "media_run_id",
        "job_count",
        "audio_artifact_count",
        "checksums",
        "provider",
        "model",
        "model_calls",
        "total_tokens",
        "latency_ms",
        "cost_status",
        "fallback_used",
    }
    for forbidden in (
        "api_key",
        "authorization",
        "reasoning_content",
        "raw_response",
        "messages",
    ):
        assert forbidden not in encoded.casefold()


def test_compose_runtime_gate_targets_current_s2_migration_and_parent_graph() -> None:
    source = (SCRIPTS / "check_compose_runtime.sh").read_text()

    assert '"20260813_0016"' in source
    assert 'PARENT_GRAPH_TOPOLOGY_VERSION == \\"motif-forge-parent.v2\\"' in source
    assert '"20260812_0012"' not in source
