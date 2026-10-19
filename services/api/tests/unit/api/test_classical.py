import hashlib

import httpx
import pytest
from application.fakes import FakeTransaction
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from motif_forge.api.classical import build_classical_router
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_capability import PianoCapability


@pytest.mark.asyncio
async def test_reviewed_score_catalog_download_import_report_and_unknown_id_boundaries():
    tx = FakeTransaction()

    async def capability():
        return PianoCapability(available=True)

    app = FastAPI()
    app.include_router(build_classical_router(tx, capability=capability))

    @app.exception_handler(ApplicationError)
    async def error(request, exc):
        return JSONResponse({"error_code": exc.code}, status_code=404)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        entry = (await client.get("/api/v1/classical-scores")).json()["data"][0]
        assert (
            entry["license"] == "Public Domain"
            and entry["measure_count"] == 16
            and entry["note_count"] == 62
        )
        xml = await client.get("/api/v1/classical-scores/" + entry["score_id"] + "/musicxml")
        assert (
            xml.status_code == 200
            and hashlib.sha256(xml.content).hexdigest() == entry["musicxml_sha256"]
        )
        rejected = await client.post(
            "/api/v1/classical-score-imports",
            json={"score_id": "unreviewed"},
            headers={"Idempotency-Key": "unreviewed-source-test"},
        )
        assert rejected.status_code == 422 and not tx.roots
        accepted = await client.post(
            "/api/v1/classical-score-imports",
            json={"score_id": entry["score_id"]},
            headers={"Idempotency-Key": "reviewed-source-test"},
        )
        assert accepted.status_code == 201
        result = accepted.json()["data"]
        report = await client.get("/api/v1/projects/" + result["project_id"] + "/classical-source")
        assert (
            report.status_code == 200
            and len(report.json()["data"]["import_report"]["note_map"]) == 62
        )
        assert report.json()["data"]["source"]["musicxml_sha256"] == entry["musicxml_sha256"]
        assert (
            await client.get("/api/v1/classical-scores/not-reviewed/musicxml")
        ).status_code == 404
