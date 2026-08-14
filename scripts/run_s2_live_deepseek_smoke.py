#!/usr/bin/env python3
"""Opt-in, budgeted live DeepSeek -> Parent Graph -> complete-export acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

import httpx
from motif_forge.agent.schemas import CompositionPlan
from motif_forge.config import Settings
from motif_forge.domain.ai_runs import (
    PLAN_HASH_VERSION_V2,
    approval_assertion_hash,
    composition_plan_content_hash,
)
from motif_forge.infrastructure.persistence.database import create_postgres_engine
from run_s2_deterministic_smoke import (
    TIMEOUT_SECONDS,
    _host_postgres_dsn,
    _request,
    _verify_lineage_and_checksums,
    _wait_for_bundle,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

REVIEWED_MODEL = "deepseek-v4-flash"
REVIEWED_MAX_OUTPUT_TOKENS = 4096
REVIEWED_MAX_ATTEMPTS = 1
MAX_MODEL_REQUESTS = 1
MAX_TOTAL_TOKENS = 12_000
ACCEPTANCE_ID = "s2-live-deepseek-acceptance-v2"
LIVE_BRIEF = {
    "schema_version": "composition-brief.v1",
    "title": "Live Observatory Drift",
    "purpose": "Instrumental background for a quiet orbital observatory sequence",
    "style": "synth_ambient",
    "duration_seconds": 84,
    "meter": "4/4",
    "target_bpm": 72,
    "target_key": "D dorian",
    "moods": ["weightless", "curious", "restrained"],
    "hard_constraints": ["four supported instrumental roles", "clear finite ending"],
    "negative_constraints": ["no vocals", "no artist imitation", "no abrupt drop"],
}


@dataclass(frozen=True, slots=True)
class LiveGuard:
    model: str
    actor: str
    assertion: str
    max_output_tokens: int = REVIEWED_MAX_OUTPUT_TOKENS
    max_attempts: int = REVIEWED_MAX_ATTEMPTS
    max_model_requests: int = MAX_MODEL_REQUESTS
    max_total_tokens: int = MAX_TOTAL_TOKENS


@dataclass(frozen=True, slots=True)
class AcceptanceKeys:
    project: str
    run: str
    resume: str


def acceptance_keys() -> AcceptanceKeys:
    """Return the immutable database idempotency identity for this paid acceptance."""

    return AcceptanceKeys(
        project=f"{ACCEPTANCE_ID}-project",
        run=f"{ACCEPTANCE_ID}-run",
        resume=f"{ACCEPTANCE_ID}-resume",
    )


def load_live_guard(environment: Mapping[str, str]) -> LiveGuard:
    if environment.get("MOTIF_FORGE_S2_LIVE", "").strip() != "1":
        raise RuntimeError("live acceptance requires explicit opt-in")
    if not environment.get("DEEPSEEK_API_KEY", "").strip():
        raise RuntimeError("live acceptance requires a configured provider key")
    model = environment.get("DEEPSEEK_MODEL", REVIEWED_MODEL).strip()
    if model != REVIEWED_MODEL:
        raise RuntimeError(f"live acceptance requires {REVIEWED_MODEL}")
    output_tokens = environment.get(
        "MOTIF_FORGE_DEEPSEEK_MAX_OUTPUT_TOKENS", ""
    ).strip()
    if output_tokens != str(REVIEWED_MAX_OUTPUT_TOKENS):
        raise RuntimeError(
            f"live acceptance requires {REVIEWED_MAX_OUTPUT_TOKENS} output tokens"
        )
    attempts = environment.get("MOTIF_FORGE_DEEPSEEK_MAX_ATTEMPTS", "").strip()
    if attempts != str(REVIEWED_MAX_ATTEMPTS):
        raise RuntimeError("live acceptance requires exactly one provider attempt")
    actor = environment.get("MOTIF_FORGE_S2_APPROVAL_ACTOR", "").strip()
    if not actor:
        raise RuntimeError("live acceptance requires an approval actor")
    assertion = environment.get("MOTIF_FORGE_S2_APPROVAL_ASSERTION", "").strip()
    if len(assertion) < 16:
        raise RuntimeError("live acceptance requires a 16+ character approval assertion")
    return LiveGuard(
        model=model,
        actor=actor,
        assertion=assertion,
        max_output_tokens=REVIEWED_MAX_OUTPUT_TOKENS,
        max_attempts=REVIEWED_MAX_ATTEMPTS,
    )


def validate_projection_budget(projection: Mapping[str, object], guard: LiveGuard) -> None:
    max_requests = projection.get("max_model_requests")
    submitted = projection.get("submitted_model_requests")
    total_tokens = projection.get("total_tokens")
    usage_status = projection.get("model_usage_status")
    if (
        not isinstance(max_requests, int)
        or max_requests > guard.max_model_requests
        or not isinstance(submitted, int)
        or submitted > guard.max_model_requests
    ):
        raise RuntimeError("live acceptance exceeded the model request budget")
    if usage_status != "known" or not isinstance(total_tokens, int):
        raise RuntimeError("live acceptance requires known model usage")
    if total_tokens > guard.max_total_tokens:
        raise RuntimeError("live acceptance exceeded the token budget")


def _required_int(value: object, field: str) -> int:
    if not isinstance(value, int):
        raise RuntimeError(f"live AI Run projection has invalid {field}")
    return value


def validate_persisted_plan(
    row: Mapping[str, object],
    *,
    pending_hash: object,
    expected_model: str,
) -> CompositionPlan:
    raw_plan = row.get("plan")
    plan = CompositionPlan.model_validate_json(json.dumps(raw_plan), strict=True)
    hash_version = row.get("hash_version")
    if hash_version != PLAN_HASH_VERSION_V2:
        raise RuntimeError("live Plan hash version is not the reviewed lossless contract")
    persisted_hash = row.get("content_hash")
    recomputed_hash = composition_plan_content_hash(
        plan, hash_version=PLAN_HASH_VERSION_V2
    )
    if persisted_hash != recomputed_hash or (
        pending_hash is not None and pending_hash != recomputed_hash
    ):
        raise RuntimeError("live Plan content hash does not match the strict Plan")
    if (
        row.get("provider") != "deepseek"
        or row.get("model") != expected_model
        or row.get("fallback_reason") is not None
    ):
        raise RuntimeError("live Plan provider/model/fallback evidence is invalid")
    return plan


def validate_persisted_approval(
    row: Mapping[str, object],
    *,
    guard: LiveGuard,
    plan_hash: str,
    expected_interrupt_ref: str | None,
) -> None:
    interrupt_ref = row.get("interrupt_ref")
    valid_interrupt = isinstance(interrupt_ref, str) and bool(interrupt_ref)
    if expected_interrupt_ref is not None:
        valid_interrupt = valid_interrupt and interrupt_ref == expected_interrupt_ref
    if (
        row.get("assertion_hash") != approval_assertion_hash(guard.assertion)
        or row.get("decision") != "approve"
        or row.get("actor_id") != guard.actor
        or row.get("expected_plan_content_hash") != plan_hash
        or not valid_interrupt
    ):
        raise RuntimeError("live persisted approval evidence is invalid")


def build_safe_summary(
    *,
    run_id: UUID,
    thread_id: str,
    revision_id: UUID,
    bundle_id: UUID,
    media_run_id: UUID,
    job_count: int,
    audio_artifact_count: int,
    checksums: Mapping[str, str],
    provider: str,
    model: str,
    model_calls: int,
    total_tokens: int,
    latency_ms: int,
    cost_status: str,
    fallback_used: bool,
) -> dict[str, object]:
    return {
        "run_id": str(run_id),
        "thread_id": thread_id,
        "revision_id": str(revision_id),
        "bundle_id": str(bundle_id),
        "media_run_id": str(media_run_id),
        "job_count": job_count,
        "audio_artifact_count": audio_artifact_count,
        "checksums": dict(checksums),
        "provider": provider,
        "model": model,
        "model_calls": model_calls,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "cost_status": cost_status,
        "fallback_used": fallback_used,
    }


def _assert_live_runtime() -> None:
    container = os.environ.get(
        "MOTIF_FORGE_S2_RESUME_CONTAINER",
        "agentic-music-workbench-resume-dispatcher-1",
    ).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise RuntimeError("MOTIF_FORGE_S2_RESUME_CONTAINER is invalid")
    command = (
        'test -n "$DEEPSEEK_API_KEY" && '
        f'test "${{DEEPSEEK_MODEL:-{REVIEWED_MODEL}}}" = "{REVIEWED_MODEL}" && '
        'test "${MOTIF_FORGE_DEEPSEEK_MAX_ATTEMPTS:-}" = '
        f'"{REVIEWED_MAX_ATTEMPTS}" && '
        'test "${MOTIF_FORGE_DEEPSEEK_MAX_OUTPUT_TOKENS:-}" = '
        f'"{REVIEWED_MAX_OUTPUT_TOKENS}"'
    )
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-c", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError("live dispatcher runtime attestation failed before API mutation")


async def _read_projection(
    client: httpx.AsyncClient, run_id: UUID
) -> dict[str, object]:
    body = await _request(client, "GET", f"/api/v1/runs/{run_id}")
    projection = body.get("data")
    if not isinstance(projection, dict):
        raise RuntimeError("live AI Run projection is missing")
    return projection


async def _wait_via_sse(
    client: httpx.AsyncClient,
    run_id: UUID,
    *,
    statuses: set[str],
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + TIMEOUT_SECONDS
    last_event_id: int | None = None
    while asyncio.get_running_loop().time() < deadline:
        projection = await _read_projection(client, run_id)
        if projection.get("status") in statuses:
            return projection
        headers = (
            {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else None
        )
        async with client.stream(
            "GET",
            f"/api/v1/runs/{run_id}/events",
            headers=headers,
            timeout=30.0,
        ) as response:
            if response.is_error:
                raise RuntimeError(
                    f"live SSE failed: status={response.status_code}"
                )
            async for line in response.aiter_lines():
                if line.startswith("id: "):
                    last_event_id = int(line.removeprefix("id: "))
                if line == "" or line.startswith(":"):
                    projection = await _read_projection(client, run_id)
                    if projection.get("status") in statuses:
                        return projection
                if asyncio.get_running_loop().time() >= deadline:
                    break
    raise TimeoutError(f"live AI Run did not reach {sorted(statuses)}")


async def _read_live_plan(engine: AsyncEngine, run_id: UUID) -> dict[str, object]:
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT plan, content_hash, hash_version, provider, model, fallback_reason "
                        "FROM app.composition_plans WHERE run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def _read_pending_interrupt_ref(engine: AsyncEngine, run_id: UUID) -> str:
    async with engine.connect() as connection:
        value = (
            await connection.execute(
                text("SELECT pending_interrupt_ref FROM app.ai_runs WHERE id=:run_id"),
                {"run_id": run_id},
            )
        ).scalar_one()
    if not isinstance(value, str) or not value:
        raise RuntimeError("live pending PlanApproval interrupt is missing")
    return value


async def _read_persisted_approval(
    engine: AsyncEngine, run_id: UUID
) -> dict[str, object]:
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT assertion_hash, decision, actor_id, "
                        "expected_plan_content_hash, interrupt_ref "
                        "FROM app.ai_run_approvals WHERE run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def _verify_persisted_usage(
    engine: AsyncEngine,
    run_id: UUID,
    *,
    expected_calls: int,
    expected_tokens: int,
) -> None:
    async with engine.connect() as connection:
        usage = (
            (
                await connection.execute(
                    text(
                        "SELECT count(*) AS calls, coalesce(sum(total_tokens), 0) AS tokens, "
                        "bool_and(status='observed' AND usage_status='known') AS all_known "
                        "FROM app.ai_model_request_reservations WHERE run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .one()
        )
    if (
        int(usage["calls"]) != expected_calls
        or int(usage["tokens"]) != expected_tokens
        or usage["all_known"] is not True
    ):
        raise RuntimeError("live persisted provider usage does not match the AI Run projection")


async def main() -> None:
    guard = load_live_guard(os.environ)
    _assert_live_runtime()
    api_url = os.environ.get("MOTIF_FORGE_API_URL", "").strip()
    if not api_url:
        raise RuntimeError("MOTIF_FORGE_API_URL is required")
    settings = Settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required")
    artifact_root = settings.artifact_root.resolve()
    if not artifact_root.is_dir():
        raise RuntimeError("ARTIFACT_ROOT_UNAVAILABLE")

    started_at = perf_counter()
    keys = acceptance_keys()
    engine = create_postgres_engine(
        _host_postgres_dsn(settings.postgres_dsn.get_secret_value())
    )
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
            project_body = await _request(
                client,
                "POST",
                "/api/v1/projects",
                key=keys.project,
                payload={"name": "S2 live DeepSeek acceptance v1"},
            )
            project = project_body.get("data")
            if not isinstance(project, dict):
                raise RuntimeError("live Project response is missing")
            project_id = UUID(str(project["project_id"]))
            run_body = await _request(
                client,
                "POST",
                f"/api/v1/projects/{project_id}/ai-runs",
                key=keys.run,
                payload={
                    "branch_id": project["active_branch_id"],
                    "base_revision_id": project["root_revision_id"],
                    "max_model_requests": guard.max_model_requests,
                    "max_total_tokens": guard.max_total_tokens,
                    "brief": LIVE_BRIEF,
                },
            )
            run = run_body.get("data")
            if not isinstance(run, dict):
                raise RuntimeError("live AI Run response is missing")
            run_id = UUID(str(run["run_id"]))

            current = await _wait_via_sse(
                client,
                run_id,
                statuses={
                    "waiting_approval",
                    "materializing",
                    "waiting_worker",
                    "succeeded",
                    "failed",
                    "rejected",
                    "cancelled",
                },
            )
            validate_projection_budget(current, guard)
            status = current.get("status")
            if status in {"failed", "rejected", "cancelled"}:
                raise RuntimeError("the durable live acceptance Run is terminal and unsuccessful")
            plan_row = await _read_live_plan(engine, run_id)
            pending_hash = (
                current.get("pending_plan_hash") if status == "waiting_approval" else None
            )
            plan = validate_persisted_plan(
                plan_row,
                pending_hash=pending_hash,
                expected_model=guard.model,
            )
            roles = {item.role.casefold().strip() for item in plan.instrumentation}
            if roles != {"pad", "melody", "bass", "rhythm"}:
                raise RuntimeError("live Plan does not contain the four reviewed roles")
            expected_interrupt_ref: str | None = None
            if status == "waiting_approval":
                expected_interrupt_ref = await _read_pending_interrupt_ref(engine, run_id)
                await _request(
                    client,
                    "POST",
                    f"/api/v1/runs/{run_id}/resume",
                    key=keys.resume,
                    payload={
                        "expected_version": current["version"],
                        "expected_plan_hash": current["pending_plan_hash"],
                        "actor_id": guard.actor,
                        "approval_assertion": guard.assertion,
                        "decision": "approve",
                        "note": "reviewed live S2 paid acceptance",
                    },
                )
            terminal = (
                current
                if status == "succeeded"
                else await _wait_via_sse(
                    client, run_id, statuses={"succeeded", "failed", "cancelled"}
                )
            )
            validate_projection_budget(terminal, guard)
            if terminal.get("status") != "succeeded" or terminal.get("fallback_reason") is not None:
                raise RuntimeError("live Parent Graph did not complete without fallback")
            approval_row = await _read_persisted_approval(engine, run_id)
            validate_persisted_approval(
                approval_row,
                guard=guard,
                plan_hash=str(plan_row["content_hash"]),
                expected_interrupt_ref=expected_interrupt_ref,
            )
            revision_id, audio, bundle, jobs, media_run = await _wait_for_bundle(engine, run_id)
            checksums = _verify_lineage_and_checksums(
                artifact_root, revision_id, audio, bundle, jobs, media_run
            )
            model_calls = _required_int(
                terminal.get("submitted_model_requests"), "submitted_model_requests"
            )
            total_tokens = _required_int(terminal.get("total_tokens"), "total_tokens")
            if model_calls < 1:
                raise RuntimeError("live acceptance has no paid provider submission")
            await _verify_persisted_usage(
                engine,
                run_id,
                expected_calls=model_calls,
                expected_tokens=total_tokens,
            )
            safe_summary = build_safe_summary(
                run_id=run_id,
                thread_id=str(terminal["thread_id"]),
                revision_id=revision_id,
                bundle_id=UUID(str(bundle["id"])),
                media_run_id=UUID(str(media_run["id"])),
                job_count=len(jobs),
                audio_artifact_count=len(audio),
                checksums=checksums,
                provider=str(plan_row["provider"]),
                model=str(plan_row["model"]),
                model_calls=model_calls,
                total_tokens=total_tokens,
                latency_ms=int((perf_counter() - started_at) * 1000),
                cost_status=str(terminal["cost_status"]),
                fallback_used=False,
            )
            print(json.dumps(safe_summary, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"S2 live smoke failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
