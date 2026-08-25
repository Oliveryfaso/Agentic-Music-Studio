#!/usr/bin/env python3
"""No-key S7 acceptance built on the proven public S2 generation flow."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from uuid import UUID

import httpx
from motif_forge.config import Settings
from motif_forge.infrastructure.persistence.database import create_postgres_engine
from sqlalchemy import text

from . import run_s2_deterministic_smoke as s2


def _assert_no_paid_runtime(environment: dict[str, str]) -> None:
    container = environment.get("MOTIF_FORGE_S2_RESUME_CONTAINER", "").strip()
    if not container:
        result = subprocess.run(
            ["docker", "compose", "ps", "-q", "resume-dispatcher"],
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        containers = [value for value in result.stdout.splitlines() if value]
        if result.returncode != 0 or len(containers) != 1:
            raise RuntimeError("S7 could not identify one live resume dispatcher")
        container = containers[0]
    environment["MOTIF_FORGE_S2_RESUME_CONTAINER"] = container
    os.environ["MOTIF_FORGE_S2_RESUME_CONTAINER"] = container
    s2._assert_no_paid_runtime()


def _s2_acceptance(environment: dict[str, str]) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.run_s2_deterministic_smoke"],
        capture_output=True,
        check=False,
        env=environment,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-2000:]
        raise RuntimeError(f"S7 generation acceptance failed: {detail}")
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError("S7 generation acceptance returned no summary")
    value = json.loads(lines[-1])
    if not isinstance(value, dict):
        raise RuntimeError("S7 generation acceptance summary is invalid")
    return value


async def main() -> None:
    api_url = os.environ.get("MOTIF_FORGE_API_URL", "http://127.0.0.1:8000").strip()
    if api_url not in {"http://127.0.0.1:8000", "http://127.0.0.1:8100"}:
        raise RuntimeError("S7 smoke requires the reviewed local API origin")
    environment = dict(os.environ)
    environment.update({
        "MOTIF_FORGE_API_URL": api_url,
        "MOTIF_FORGE_S2_APPROVAL_ACTOR": "portfolio-owner",
        "MOTIF_FORGE_S2_APPROVAL_ASSERTION": "I approve this deterministic portfolio plan.",
    })
    _assert_no_paid_runtime(environment)
    generated = _s2_acceptance(environment)
    run_id = UUID(str(generated["run_id"]))
    revision_id = UUID(str(generated["revision_id"]))
    media_run_id = UUID(str(generated["media_run_id"]))

    async with httpx.AsyncClient(base_url=api_url, timeout=30) as client:
        inspection_response = await client.get(f"/api/v1/runs/{run_id}/inspect")
        inspection_response.raise_for_status()
        inspection = inspection_response.json()["data"]
        project_id = UUID(inspection["run"]["project_id"])
        export_response = await client.get(
            f"/api/v1/projects/{project_id}/revisions/{revision_id}/exports"
        )
        export_response.raise_for_status()
        export = export_response.json()["data"]
        if export["status"] != "ready" or len(export["steps"]) != 7:
            raise RuntimeError("S7 Export projection is not ready with seven steps")
        audio_file = next((item for item in export["files"] if item["artifact_id"]), None)
        manifest_file = next(
            (item for item in export["files"] if item["category"] == "manifest"), None
        )
        if audio_file is None or manifest_file is None:
            raise RuntimeError("S7 Export projection lacks downloadable audio or manifest")
        if not audio_file["content_url"].startswith("/api/v1/audio-artifacts/"):
            raise RuntimeError("S7 audio did not expose the public content endpoint")
        if "/files/" not in manifest_file["content_url"]:
            raise RuntimeError("S7 manifest did not expose the public Bundle file endpoint")
        audio_response = await client.get(audio_file["content_url"])
        manifest_response = await client.get(manifest_file["content_url"])
        audio_response.raise_for_status()
        manifest_response.raise_for_status()
        if not audio_response.content or not manifest_response.content:
            raise RuntimeError("S7 downloaded an empty delivery file")

    settings = Settings()
    if settings.postgres_dsn is None:
        raise RuntimeError("MOTIF_FORGE_POSTGRES_DSN is required")
    engine = create_postgres_engine(
        s2._host_postgres_dsn(settings.postgres_dsn.get_secret_value())
    )
    try:
        async with engine.connect() as connection:
            facts = (
                await connection.execute(
                    text(
                        "SELECT submitted_model_requests, total_tokens, "
                        "(SELECT count(*) FROM app.jobs WHERE run_id=:media_run_id) jobs, "
                        "(SELECT count(*) FROM app.artifacts WHERE project_id=:project_id "
                        " AND revision_id=:revision_id) audio "
                        "FROM app.ai_runs WHERE id=:run_id"
                    ),
                    {"run_id": run_id, "media_run_id": media_run_id,
                     "project_id": project_id, "revision_id": revision_id},
                )
            ).mappings().one()
        if tuple(map(int, facts.values())) != (0, 0, 7, 6):
            raise RuntimeError("S7 authoritative usage or media counts differ")
    finally:
        await engine.dispose()

    print(json.dumps({
        "status": "succeeded", "project_id": str(project_id), "run_id": str(run_id),
        "revision_id": str(revision_id), "bundle_id": export["bundle"]["bundle_id"],
        "job_count": 7, "audio_artifact_count": 6,
        "submitted_model_requests": 0, "total_tokens": 0,
        "inspector_events": len(inspection["timeline"]), "export_steps": 7,
    }, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
