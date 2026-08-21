#!/usr/bin/env python3
"""No-Key public S5 Candidate/Critic/Selection/export acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from motif_forge.config import Settings
from motif_forge.infrastructure.persistence.database import create_postgres_engine
from sqlalchemy import text

from . import run_s2_deterministic_smoke as s2


def run_contract_fixture() -> dict[str, int]:
    """Exercise the finite count contract without services or model calls."""

    candidate_families = {"a", "b"}
    snapshots = ["a-root", "b-root", "b-improved"]
    selection_previews = {"a-final", "b-final"}
    export_steps = ("master", "pad", "melody", "bass", "rhythm", "mp3", "bundle")
    return {
        "provider_requests": 0,
        "provider_tokens": 0,
        "candidate_snapshots": len(snapshots),
        "selection_previews": len(selection_previews),
        "selected_revisions": int(len(candidate_families) == 2),
        "export_jobs": len(export_steps),
        "audio_artifacts": len(export_steps) - 1,
        "bundles": 1,
    }


async def _candidate_facts(engine, run_id: UUID) -> dict[str, int]:  # type: ignore[no-untyped-def]
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(DISTINCT candidate_id) FROM app.candidate_snapshots "
                    " WHERE source_run_id=:run_id) AS candidate_families, "
                    "(SELECT count(*) FROM app.candidate_snapshots "
                    " WHERE source_run_id=:run_id) AS candidate_snapshots, "
                    "(SELECT count(*) FROM app.candidate_snapshots "
                    " WHERE source_run_id=:run_id AND parent_candidate_snapshot_id IS NOT NULL) "
                    " AS repair_children, "
                    "(SELECT count(*) FROM app.preview_candidates "
                    " WHERE source_run_id=:run_id) AS selection_previews, "
                    "(SELECT count(*) FROM app.project_revisions "
                    " WHERE source_run_id=:run_id) AS selected_revisions, "
                    "(SELECT count(*) FROM app.composition_materialization_receipts "
                    " WHERE run_id=:run_id) AS receipts, "
                    "(SELECT count(*) FROM app.ai_model_request_reservations "
                    " WHERE run_id=:run_id) AS reservations"
                ),
                {"run_id": run_id},
            )
        ).mappings().one()
    return {key: int(value) for key, value in row.items()}


async def main() -> None:
    api_url = os.environ.get("MOTIF_FORGE_API_URL", "").strip()
    actor = os.environ.get("MOTIF_FORGE_S5_APPROVAL_ACTOR", "").strip()
    assertion = os.environ.get("MOTIF_FORGE_S5_APPROVAL_ASSERTION", "").strip()
    artifact_container = os.environ.get("MOTIF_FORGE_S5_ARTIFACT_CONTAINER", "").strip()
    if not api_url or not actor or len(assertion) < 16:
        raise RuntimeError("S5 API URL and explicit 16+ character approval are required")
    s2._assert_no_paid_runtime()
    settings = Settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required")
    artifact_root = Path(settings.artifact_root).resolve()
    if not artifact_root.is_dir():
        raise RuntimeError("ARTIFACT_ROOT_UNAVAILABLE")
    engine = create_postgres_engine(
        s2._host_postgres_dsn(settings.postgres_dsn.get_secret_value())
    )
    invocation = uuid4().hex
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
            project_body = await s2._request(
                client, "POST", "/api/v1/projects", key=f"s5-project-{invocation}",
                payload={"name": f"S5 deterministic smoke {invocation[:8]}"},
            )
            project = project_body.get("data")
            if not isinstance(project, dict):
                raise RuntimeError("S5 Project response is missing")
            project_id = UUID(str(project["project_id"]))
            run_body = await s2._request(
                client, "POST", f"/api/v1/projects/{project_id}/ai-runs",
                key=f"s5-run-{invocation}",
                payload={
                    "branch_id": project["active_branch_id"],
                    "base_revision_id": project["root_revision_id"],
                    "brief": {**s2.BRIEF, "title": "S5 Candidate Orbit"},
                },
            )
            run_data = run_body.get("data")
            if not isinstance(run_data, dict):
                raise RuntimeError("S5 Run response is missing")
            run_id = UUID(str(run_data["run_id"]))
            pending = await s2._wait_for_run(client, run_id, statuses={"waiting_approval"})
            await s2._request(
                client, "POST", f"/api/v1/runs/{run_id}/resume",
                key=f"s5-plan-approval-{invocation}",
                payload={
                    "expected_version": pending["version"],
                    "expected_plan_hash": pending["pending_plan_hash"],
                    "actor_id": actor, "approval_assertion": assertion,
                    "decision": "approve", "note": "S5 no-Key Plan approval",
                },
            )
            await s2._select_candidate_if_required(
                client, run_id, actor=actor, assertion=assertion,
                idempotency_key=f"s5-candidate-selection-{invocation}",
            )
            revision_id, audio, bundle, jobs, media_run = await s2._wait_for_bundle(
                engine, run_id
            )
            terminal = await s2._wait_for_run(
                client, run_id, statuses={"succeeded", "failed"}
            )
            if terminal["status"] != "succeeded":
                raise RuntimeError(f"S5 Parent thread failed: {terminal.get('error_code')}")
            facts = await _candidate_facts(engine, run_id)
            if facts["candidate_families"] != 2:
                raise RuntimeError("S5 requires exactly two stable candidate families")
            if facts["candidate_snapshots"] not in {2, 3} or facts["repair_children"] not in {0, 1}:
                raise RuntimeError("S5 violated its one-Repair Snapshot bound")
            if facts["selection_previews"] != 2:
                raise RuntimeError("S5 requires exactly two final selection Previews")
            if facts["selected_revisions"] != 1 or facts["receipts"] != 1:
                raise RuntimeError("S5 must materialize exactly one selected Revision")
            if facts["reservations"] != 0 or terminal["submitted_model_requests"] != 0:
                raise RuntimeError("S5 no-Key smoke recorded a provider request")
            if terminal["total_tokens"] != 0:
                raise RuntimeError("S5 no-Key smoke recorded provider tokens")
            checksums = s2._verify_lineage_and_checksums(
                artifact_root, revision_id, audio, bundle, jobs, media_run,
                artifact_container or None,
            )
            summary = {
                "project_id": str(project_id), "run_id": str(run_id),
                "status": terminal["status"], "revision_id": str(revision_id),
                **facts, "export_jobs": len(jobs), "audio_artifacts": len(audio),
                "bundle_id": str(bundle["id"]), "media_run_id": str(media_run["id"]),
                "checksums": checksums,
                "provider_requests": terminal["submitted_model_requests"],
                "provider_tokens": terminal["total_tokens"],
            }
            if len(json.dumps(summary)) >= 4096:
                raise RuntimeError("S5 acceptance summary is not bounded")
            print(json.dumps(summary, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"S5 deterministic smoke failed: {exc}", file=sys.stderr)
        raise
