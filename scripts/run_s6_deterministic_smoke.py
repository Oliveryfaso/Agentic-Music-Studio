#!/usr/bin/env python3
"""No-Key public S6 manual/undo/L0/L2 edit acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from uuid import UUID, uuid4

import httpx
from motif_forge.config import Settings
from motif_forge.infrastructure.persistence.database import create_postgres_engine
from sqlalchemy import text

from . import run_s2_deterministic_smoke as s2


def run_contract_fixture() -> dict[str, int]:
    return {
        "manual_revisions": 2,
        "undo_revisions": 1,
        "l0_revisions": 1,
        "l2_previews": 1,
        "l2_approved_revisions": 1,
        "provider_requests": 0,
        "provider_tokens": 0,
    }


def _attest_no_paid_runtime() -> None:
    if not os.environ.get("MOTIF_FORGE_S2_RESUME_CONTAINER", "").strip():
        result = subprocess.run(
            ["docker", "compose", "ps", "-q", "resume-dispatcher"],
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        container_ids = [value for value in result.stdout.splitlines() if value]
        if result.returncode != 0 or len(container_ids) != 1:
            raise RuntimeError("S6 could not identify the live resume dispatcher")
        os.environ["MOTIF_FORGE_S2_RESUME_CONTAINER"] = container_ids[0]
    s2._assert_no_paid_runtime()


async def _wait(client: httpx.AsyncClient, run_id: UUID, statuses: set[str]) -> dict:
    for _ in range(1200):
        response = await client.get(f"/api/v1/runs/{run_id}")
        response.raise_for_status()
        run = response.json()["data"]
        if run["status"] in statuses:
            return run
        await asyncio.sleep(0.25)
    raise RuntimeError(f"S6 Run {run_id} did not reach {sorted(statuses)}")


async def _wait_for_revision(client: httpx.AsyncClient, run_id: UUID) -> dict:
    for _ in range(1200):
        response = await client.get(f"/api/v1/runs/{run_id}")
        response.raise_for_status()
        run = response.json()["data"]
        if run.get("revision_id") or run["status"] in {"failed", "cancelled"}:
            return run
        await asyncio.sleep(0.25)
    raise RuntimeError(f"S6 fixture Run {run_id} did not materialize a Revision")


async def _post(
    client: httpx.AsyncClient, path: str, payload: dict, key: str
) -> dict:
    response = await client.post(path, json=payload, headers={"Idempotency-Key": key})
    if response.is_error:
        raise RuntimeError(
            f"S6 public request failed ({response.status_code}) at {path}: "
            f"{response.text[:1000]}"
        )
    response.raise_for_status()
    return response.json()["data"]


async def main() -> None:
    api_url = os.environ.get("MOTIF_FORGE_API_URL", "http://127.0.0.1:8000").strip()
    if api_url not in {"http://127.0.0.1:8000", "http://127.0.0.1:8100"}:
        raise RuntimeError("S6 smoke requires the reviewed local API origin")
    _attest_no_paid_runtime()
    settings = Settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required")
    engine = create_postgres_engine(
        s2._host_postgres_dsn(settings.postgres_dsn.get_secret_value())
    )
    invocation = uuid4().hex
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=30) as client:
            project = await _post(
                client, "/api/v1/projects", {"name": f"S6 smoke {invocation[:8]}"},
                f"s6-project-{invocation}",
            )
            project_id = UUID(project["project_id"])
            branch_id = project["active_branch_id"]
            generated = await _post(
                client, f"/api/v1/projects/{project_id}/ai-runs",
                {"branch_id": branch_id, "base_revision_id": project["root_revision_id"],
                 "brief": s2.BRIEF}, f"s6-generate-{invocation}",
            )
            generated_id = UUID(generated["run_id"])
            pending = await _wait(client, generated_id, {"waiting_approval", "failed"})
            if pending["status"] != "waiting_approval":
                raise RuntimeError(f"S6 fixture generation failed: {pending.get('error_code')}")
            await _post(
                client, f"/api/v1/runs/{generated_id}/resume",
                {"expected_version": pending["version"],
                 "expected_plan_hash": pending["pending_plan_hash"],
                 "actor_id": "portfolio-owner",
                 "approval_assertion": "I approve this deterministic S6 fixture plan.",
                 "decision": "approve", "note": "S6 fixture approval"},
                f"s6-generate-approve-{invocation}",
            )
            await s2._select_candidate_if_required(
                client, generated_id, actor="portfolio-owner",
                assertion="I approve this deterministic S6 fixture candidate.",
                idempotency_key=f"s6-generate-select-{invocation}",
            )
            generated_materialized = await _wait_for_revision(client, generated_id)
            if not generated_materialized.get("revision_id"):
                raise RuntimeError(
                    "S6 fixture did not materialize a Revision: "
                    f"{generated_materialized.get('error_code')}"
                )
            generated_revision_id = generated_materialized["revision_id"]
            if generated_materialized["status"] == "waiting_worker":
                await _post(
                    client, f"/api/v1/runs/{generated_id}/cancel",
                    {"expected_version": generated_materialized["version"]},
                    f"s6-fixture-cancel-{invocation}",
                )
            studio_response = await client.get(
                f"/api/v1/projects/{project_id}/revisions/{generated_revision_id}/studio"
            )
            studio_response.raise_for_status()
            studio = studio_response.json()["data"]
            editable_track = next(
                track for track in studio["arrangement_ir"]["tracks"] if track["clips"]
            )
            track_id = UUID(editable_track["track_id"])

            def set_gain() -> dict:
                return {
                    "command_id": str(uuid4()), "command_type": "set_track_param",
                    "schema_version": "editor-command.v1", "actor_kind": "human",
                    "client_sequence": 0,
                    "selection": {"track_ids": [str(track_id)],
                                  "start_tick": 0, "end_tick": 1920},
                    "payload": {"track_id": str(track_id), "parameter": "gain_db",
                                "value": -1.0},
                }
            seeded = await _post(
                client, f"/api/v1/projects/{project_id}/command-batches",
                {"branch_id": branch_id, "base_revision_id": generated_revision_id,
                 "commands": [set_gain()], "client_sequence": 0,
                 "reason": "S6_SMOKE_SEED"}, f"s6-seed-{invocation}",
            )
            undone = await _post(
                client, f"/api/v1/projects/{project_id}/undo",
                {"branch_id": branch_id, "base_revision_id": seeded["revision_id"],
                 "target_revision_id": seeded["revision_id"]}, f"s6-undo-{invocation}",
            )
            base = await _post(
                client, f"/api/v1/projects/{project_id}/command-batches",
                {"branch_id": branch_id, "base_revision_id": undone["revision_id"],
                 "commands": [set_gain()], "client_sequence": 0,
                 "reason": "S6_SMOKE_EDIT_BASE"}, f"s6-base-{invocation}",
            )

            async def create_edit(base_revision_id: str, intent: str, suffix: str) -> dict:
                return await _post(
                    client, f"/api/v1/projects/{project_id}/ai-runs",
                    {"branch_id": branch_id, "base_revision_id": base_revision_id,
                     "run_type": "edit", "brief": None,
                     "edit_request": {"intent": intent,
                        "selection": {"track_ids": [str(track_id)],
                                      "start_tick": 0, "end_tick": 1920},
                        "locked_ranges": [], "allow_local_catalog": True, "seed": 0},
                     "max_model_requests": 1, "max_total_tokens": 4000},
                    f"s6-{suffix}-{invocation}",
                )

            l0 = await create_edit(base["revision_id"], "把这里的 Pad 降低 2 dB", "l0")
            l0_terminal = await _wait(client, UUID(l0["run_id"]), {"succeeded", "failed"})
            if l0_terminal["status"] != "succeeded" or not l0_terminal["revision_id"]:
                raise RuntimeError(f"S6 L0 edit failed: {l0_terminal.get('error_code')}")

            l2 = await create_edit(
                l0_terminal["revision_id"],
                "把选中轨道的音色改成 builtin:glass-pluck", "l2",
            )
            waiting = await _wait(
                client, UUID(l2["run_id"]), {"waiting_edit_approval", "failed"}
            )
            preview = waiting.get("edit_preview")
            if waiting["status"] != "waiting_edit_approval" or not preview:
                raise RuntimeError(f"S6 L2 Preview failed: {waiting.get('error_code')}")
            if preview["preview_availability"] != "available" or not preview["preview_artifact_id"]:
                raise RuntimeError("S6 L2 approval was exposed without a real Preview Artifact")
            await _post(
                client, f"/api/v1/runs/{l2['run_id']}/edit-decision",
                {"action": "approve", "preview_id": preview["preview_id"],
                 "expected_candidate_content_hash": preview["candidate_content_hash"],
                 "actor_id": "portfolio-owner",
                 "approval_assertion": "I approve this rendered S6 edit.", "note": ""},
                f"s6-l2-approve-{invocation}",
            )
            l2_terminal = await _wait(client, UUID(l2["run_id"]), {"succeeded", "failed"})
            if l2_terminal["status"] != "succeeded" or not l2_terminal["revision_id"]:
                raise RuntimeError(f"S6 L2 approval failed: {l2_terminal.get('error_code')}")
            if any(run["submitted_model_requests"] != 0 or run["total_tokens"] != 0
                   for run in (l0_terminal, l2_terminal)):
                raise RuntimeError("S6 no-Key smoke recorded provider usage")

            async with engine.connect() as connection:
                facts = (await connection.execute(text(
                    "SELECT "
                    "(SELECT count(*) FROM app.ai_runs WHERE project_id=:project_id "
                    " AND run_type='edit') edit_runs, "
                    "(SELECT count(*) FROM app.preview_candidates "
                    " WHERE project_id=:project_id AND source_run_id IN "
                    " (SELECT id FROM app.ai_runs WHERE project_id=:project_id "
                    "  AND run_type='edit')) previews"
                ), {"project_id": project_id})).mappings().one()
            if int(facts["edit_runs"]) != 2 or int(facts["previews"]) != 1:
                raise RuntimeError("S6 durable edit counts differ from the bounded contract")
            print(json.dumps({
                "project_id": str(project_id), "track_id": str(track_id),
                "l0_run_id": l0["run_id"], "l0_revision_id": l0_terminal["revision_id"],
                "l2_run_id": l2["run_id"], "l2_preview_id": preview["preview_id"],
                "l2_preview_artifact_id": preview["preview_artifact_id"],
                "l2_revision_id": l2_terminal["revision_id"],
                "provider_requests": 0, "provider_tokens": 0,
            }, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"S6 deterministic smoke failed: {exc}", file=sys.stderr)
        raise
