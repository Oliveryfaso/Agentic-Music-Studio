#!/usr/bin/env python3
"""No-cost HTTP -> Parent Graph -> queued complete-export acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import httpx
from motif_forge.config import Settings
from motif_forge.infrastructure.persistence.database import create_postgres_engine
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

TIMEOUT_SECONDS = 480.0
BRIEF = {
    "schema_version": "composition-brief.v1",
    "title": "S2 Deterministic Orbit",
    "purpose": "Instrumental background for a quiet orbital observatory",
    "style": "synth_ambient",
    "duration_seconds": 120,
    "meter": "4/4",
    "target_bpm": 72,
    "target_key": "D dorian",
    "moods": ["weightless", "curious"],
    "hard_constraints": ["avoid clipping"],
    "negative_constraints": ["no abrupt drop"],
}


def _validated_container_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise RuntimeError("S2 runtime container name is invalid")
    return value


def _container_artifact_path(storage_key: str) -> str:
    key = PurePosixPath(storage_key)
    if (
        key.is_absolute()
        or ".." in key.parts
        or not key.parts
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", storage_key)
    ):
        raise RuntimeError("S2 Artifact storage key is invalid")
    return f"/artifacts/{key.as_posix()}"


def _physical_digest(
    artifact_root: Path, storage_key: str, artifact_container: str | None
) -> str:
    if artifact_container is None:
        return hashlib.sha256((artifact_root / storage_key).read_bytes()).hexdigest()
    result = subprocess.run(
        [
            "docker",
            "exec",
            _validated_container_name(artifact_container),
            "sha256sum",
            _container_artifact_path(storage_key),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    digest = result.stdout.split(maxsplit=1)[0] if result.returncode == 0 else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("S2 physical Artifact checksum command failed")
    return digest


def _physical_manifest_exists(
    artifact_root: Path, storage_key: str, artifact_container: str | None
) -> bool:
    if artifact_container is None:
        return (artifact_root / storage_key).is_file()
    result = subprocess.run(
        [
            "docker",
            "exec",
            _validated_container_name(artifact_container),
            "test",
            "-f",
            _container_artifact_path(storage_key),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    return result.returncode == 0


def _assert_no_paid_runtime() -> None:
    """Fail before any API mutation unless the live dispatcher has no provider key."""

    container = os.environ.get(
        "MOTIF_FORGE_S2_RESUME_CONTAINER",
        "agentic-music-workbench-resume-dispatcher-1",
    ).strip()
    container = _validated_container_name(container)
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-c", 'test -z "$DEEPSEEK_API_KEY"'],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError("S2 deterministic runtime attestation failed before API mutation")


def _host_postgres_dsn(dsn: str) -> str:
    """Translate only the Compose-internal PostgreSQL host for a host-run smoke."""

    url = make_url(dsn)
    if url.host == "postgres":
        url = url.set(host="127.0.0.1")
    return url.render_as_string(hide_password=False)


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    key: str | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    headers = {"Idempotency-Key": key} if key else None
    response = await client.request(method, path, headers=headers, json=payload)
    if response.is_error:
        raise RuntimeError(
            f"S2 API request failed: method={method} path={path} status={response.status_code}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("S2 API returned a non-object response")
    return body


async def _wait_for_run(
    client: httpx.AsyncClient,
    run_id: UUID,
    *,
    statuses: set[str],
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        body = await _request(client, "GET", f"/api/v1/runs/{run_id}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("S2 Run projection is missing")
        if data.get("status") in statuses:
            return data
        await asyncio.sleep(0.25)
    raise TimeoutError(f"S2 Run did not reach {sorted(statuses)}: {run_id}")


async def _select_candidate_if_required(
    client: httpx.AsyncClient,
    run_id: UUID,
    *,
    actor: str,
    assertion: str,
    idempotency_key: str,
) -> None:
    """Advance the current S5 HITL when the same public S2 path exposes it."""

    deadline = asyncio.get_running_loop().time() + TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        body = await _request(client, "GET", f"/api/v1/runs/{run_id}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("S2 Run projection is missing during CandidateSelection")
        if data.get("revision_id") is not None or data.get("status") in {"succeeded", "failed"}:
            return
        if data.get("pending_action") == "select_candidate":
            candidates = data.get("candidates")
            critique = data.get("critique")
            if not isinstance(candidates, list) or len(candidates) != 2:
                raise RuntimeError("S5 CandidateSelection requires exactly two Previews")
            recommended = (
                critique.get("recommended_candidate_id")
                if isinstance(critique, dict)
                else None
            )
            selected = next(
                (item for item in candidates if item.get("candidate_id") == recommended),
                candidates[0],
            )
            if selected.get("preview_availability") != "available":
                raise RuntimeError("S5 recommended Candidate Preview is unavailable")
            await _request(
                client,
                "POST",
                f"/api/v1/runs/{run_id}/select-candidate",
                key=idempotency_key,
                payload={
                    "expected_version": data["version"],
                    "preview_id": selected["preview_id"],
                    "expected_candidate_id": selected["candidate_id"],
                    "expected_candidate_content_hash": selected[
                        "candidate_content_hash"
                    ],
                    "actor_id": actor,
                    "selection_assertion": assertion,
                    "decision": "select",
                    "note": "deterministic S5 candidate selection",
                },
            )
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"S5 CandidateSelection did not become ready: {run_id}")


async def _wait_for_bundle(
    engine: AsyncEngine, run_id: UUID
) -> tuple[
    UUID,
    list[dict[str, object]],
    dict[str, object],
    list[dict[str, object]],
    dict[str, object],
]:
    deadline = asyncio.get_running_loop().time() + TIMEOUT_SECONDS
    query = text(
        "SELECT r.revision_id FROM app.composition_materialization_receipts r "
        "JOIN app.project_revisions pr ON pr.id=r.revision_id "
        "WHERE r.run_id=:run_id AND pr.source_run_id=:run_id"
    )
    while asyncio.get_running_loop().time() < deadline:
        async with engine.connect() as connection:
            revision_id = (await connection.execute(query, {"run_id": run_id})).scalar_one_or_none()
            if revision_id is not None:
                audio = (
                    (
                        await connection.execute(
                            text(
                                "SELECT id, revision_id, arrangement_hash, quality_profile, "
                                "storage_key, content_hash, source_job_id FROM app.artifacts "
                                "WHERE revision_id=:revision_id ORDER BY quality_profile, id"
                            ),
                            {"revision_id": revision_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                bundle = (
                    (
                        await connection.execute(
                            text(
                                "SELECT id, revision_id, arrangement_hash, storage_prefix, "
                                "input_artifact_ids, source_job_id "
                                "FROM app.export_bundle_artifacts "
                                "WHERE revision_id=:revision_id"
                            ),
                            {"revision_id": revision_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                media_run = (
                    (
                        await connection.execute(
                            text(
                                "SELECT id, thread_id, run_type, status FROM app.runs "
                                "WHERE project_id=(SELECT project_id FROM app.ai_runs "
                                "WHERE id=:run_id) AND run_type='complete_song_export.v1' "
                                "ORDER BY created_at DESC, id DESC LIMIT 1"
                            ),
                            {"run_id": run_id},
                        )
                    ).mappings().one_or_none()
                )
                jobs = []
                if media_run is not None:
                    jobs = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT id, run_id, status, output_quality_profile, created_at "
                                    "FROM app.jobs WHERE run_id=:media_run_id "
                                    "ORDER BY created_at, id"
                                ),
                                {"media_run_id": media_run["id"]},
                            )
                        ).mappings().all()
                    )
                plan_count = (
                    await connection.execute(
                        text("SELECT count(*) FROM app.composition_plans WHERE run_id=:run_id"),
                        {"run_id": run_id},
                    )
                ).scalar_one()
                if (
                    bundle is not None
                    and len(audio) == 6
                    and len(jobs) == 7
                    and plan_count == 1
                    and media_run is not None
                ):
                    return (
                        UUID(str(revision_id)),
                        [dict(row) for row in audio],
                        dict(bundle),
                        [dict(row) for row in jobs],
                        dict(media_run),
                    )
        await asyncio.sleep(0.25)
    raise TimeoutError(f"S2 complete export did not finish: {run_id}")


def _verify_lineage_and_checksums(
    artifact_root: Path,
    revision_id: UUID,
    audio: list[dict[str, object]],
    bundle: dict[str, object],
    jobs: list[dict[str, object]],
    media_run: dict[str, object],
    artifact_container: str | None = None,
) -> dict[str, str]:
    profiles = [str(row["quality_profile"]) for row in audio]
    if profiles.count("canonical-master.v1") != 1:
        raise RuntimeError("S2 export requires one canonical Master")
    if profiles.count("canonical-stem.v1") != 4:
        raise RuntimeError("S2 export requires four canonical Stems")
    if profiles.count("delivery-mp3.v1") != 1:
        raise RuntimeError("S2 export requires one delivery MP3")
    arrangement_hashes = {str(row["arrangement_hash"]) for row in audio}
    arrangement_hashes.add(str(bundle["arrangement_hash"]))
    if len(arrangement_hashes) != 1 or UUID(str(bundle["revision_id"])) != revision_id:
        raise RuntimeError("S2 Artifact lineage does not match one approved Revision")
    ids = {str(row["id"]) for row in audio}
    input_artifact_ids = bundle["input_artifact_ids"]
    if not isinstance(input_artifact_ids, list):
        raise RuntimeError("S2 Bundle input Artifact set is malformed")
    if ids != {str(item) for item in input_artifact_ids}:
        raise RuntimeError("S2 Bundle input Artifact set is not authoritative")
    job_ids = {str(row["id"]) for row in jobs}
    source_job_ids = {str(row["source_job_id"]) for row in audio}
    source_job_ids.add(str(bundle["source_job_id"]))
    run_ids = {str(row["run_id"]) for row in jobs}
    if source_job_ids != job_ids or len(run_ids) != 1:
        raise RuntimeError("S2 Artifacts are not bound to the exact seven export Jobs")
    if any(row["status"] != "succeeded" for row in jobs):
        raise RuntimeError("S2 export contains a non-succeeded Job")
    if str(media_run["id"]) not in run_ids or media_run["run_type"] != "complete_song_export.v1":
        raise RuntimeError("S2 Jobs do not belong to one exact complete-export Media Run")
    checksums: dict[str, str] = {}
    for row in audio:
        digest = _physical_digest(
            artifact_root, str(row["storage_key"]), artifact_container
        )
        if digest != row["content_hash"]:
            raise RuntimeError(f"S2 physical checksum mismatch: {row['id']}")
        checksums[str(row["id"])] = digest
    manifest_key = f"{bundle['storage_prefix']}/export-manifest.json"
    if not _physical_manifest_exists(artifact_root, manifest_key, artifact_container):
        raise RuntimeError("S2 physical Bundle manifest is missing")
    return checksums


async def main() -> None:
    api_url = os.environ.get("MOTIF_FORGE_API_URL", "").strip()
    actor = os.environ.get("MOTIF_FORGE_S2_APPROVAL_ACTOR", "").strip()
    assertion = os.environ.get("MOTIF_FORGE_S2_APPROVAL_ASSERTION", "").strip()
    artifact_container = os.environ.get("MOTIF_FORGE_S2_ARTIFACT_CONTAINER", "").strip()
    if not api_url:
        raise RuntimeError("MOTIF_FORGE_API_URL is required")
    if not actor or len(assertion) < 16:
        raise RuntimeError(
            "MOTIF_FORGE_S2_APPROVAL_ACTOR and MOTIF_FORGE_S2_APPROVAL_ASSERTION "
            "(16+ chars) are required"
        )
    _assert_no_paid_runtime()
    settings = Settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required")
    artifact_root = settings.artifact_root.resolve()
    if not artifact_root.is_dir():
        raise RuntimeError("ARTIFACT_ROOT_UNAVAILABLE")
    invocation = uuid4().hex
    engine = create_postgres_engine(
        _host_postgres_dsn(settings.postgres_dsn.get_secret_value())
    )
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
            project_body = await _request(
                client,
                "POST",
                "/api/v1/projects",
                key=f"s2-project-{invocation}",
                payload={"name": f"S2 deterministic smoke {invocation[:8]}"},
            )
            project = project_body["data"]
            if not isinstance(project, dict):
                raise RuntimeError("S2 Project response is missing")
            project_id = UUID(str(project["project_id"]))
            run_body = await _request(
                client,
                "POST",
                f"/api/v1/projects/{project_id}/ai-runs",
                key=f"s2-run-{invocation}",
                payload={
                    "branch_id": project["active_branch_id"],
                    "base_revision_id": project["root_revision_id"],
                    "brief": BRIEF,
                },
            )
            run = run_body["data"]
            if not isinstance(run, dict):
                raise RuntimeError("S2 AI Run response is missing")
            run_id = UUID(str(run["run_id"]))
            pending = await _wait_for_run(client, run_id, statuses={"waiting_approval"})
            if pending.get("pending_action") != "approve_plan" or not pending.get(
                "pending_plan_hash"
            ):
                raise RuntimeError("S2 persisted PlanApproval interrupt is incomplete")
            await _request(
                client,
                "POST",
                f"/api/v1/runs/{run_id}/resume",
                key=f"s2-resume-{invocation}",
                payload={
                    "expected_version": pending["version"],
                    "expected_plan_hash": pending["pending_plan_hash"],
                    "actor_id": actor,
                    "approval_assertion": assertion,
                    "decision": "approve",
                    "note": "deterministic S2 smoke approval",
                },
            )
            await _select_candidate_if_required(
                client,
                run_id,
                actor=actor,
                assertion=assertion,
                idempotency_key=f"s5-select-{invocation}",
            )
            revision_id, audio, bundle, jobs, media_run = await _wait_for_bundle(engine, run_id)
            terminal = await _wait_for_run(client, run_id, statuses={"succeeded", "failed"})
            if terminal["status"] != "succeeded":
                raise RuntimeError(f"S2 Parent thread failed: {terminal.get('error_code')}")
            async with engine.connect() as connection:
                reservation_count = (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM app.ai_model_request_reservations "
                            "WHERE run_id=:run_id"
                        ),
                        {"run_id": run_id},
                    )
                ).scalar_one()
            no_paid_model_usage = (
                reservation_count == 0
                and terminal["submitted_model_requests"] == 0
                and terminal["total_tokens"] == 0
            )
            if not no_paid_model_usage:
                raise RuntimeError("S2 deterministic smoke unexpectedly recorded paid model usage")
            checksums = _verify_lineage_and_checksums(
                artifact_root,
                revision_id,
                audio,
                bundle,
                jobs,
                media_run,
                artifact_container or None,
            )
            print(
                json.dumps(
                    {
                        "run_id": str(run_id),
                        "thread_id": terminal["thread_id"],
                        "status": terminal["status"],
                        "revision_id": str(revision_id),
                        "audio_artifact_count": len(audio),
                        "bundle_id": str(bundle["id"]),
                        "media_run_id": str(media_run["id"]),
                        "job_count": len(jobs),
                        "checksums": checksums,
                        "model_calls": terminal["submitted_model_requests"],
                        "tokens": terminal["total_tokens"],
                        "cost_status": terminal["cost_status"],
                        "no_paid_model_usage": no_paid_model_usage,
                    },
                    sort_keys=True,
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"S2 deterministic smoke failed: {exc}", file=sys.stderr)
        raise
