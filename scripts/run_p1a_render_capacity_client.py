"""Host HTTP + adapter acceptance; no Settings, DB, models or speaker playback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

import httpx
from motif_forge.application.rendering import build_canonical_render_payload
from motif_forge.audio.chromium_render import ChromiumRenderClient, ChromiumRenderError
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.render_capacity import estimate_render_capacity
from motif_forge.domain.revisions import create_root_state


def phase(name: str) -> None:
    print(json.dumps({"phase": name}), flush=True)


async def main(output: Path, origin: str) -> None:
    graph = json.loads((output / "five-minute-graph.json").read_text())
    base = create_root_state(UUID(int=1901), created_by="p1a:probe").revision
    arrangement = build_s1_composition(base.project_id, seed=42).arrangement
    base = base.model_copy(
        update={
            "arrangement_ir": arrangement,
            "content_hash": arrangement_content_hash(arrangement),
        }
    )
    payload = build_canonical_render_payload(base, seed=42).model_copy(
        update={
            "audio_graph": graph,
            "audio_graph_hash": hashlib.sha256(
                json.dumps(
                    graph, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "maximum_output_bytes": estimate_render_capacity(graph).output_limit_bytes,
        }
    )
    client = ChromiumRenderClient(
        artifact_root=output / "artifacts", temp_root=output / "temp", service_url=origin
    )
    phase("five-minute")
    started = time.perf_counter()
    result = await client.render(job_id=UUID(int=1902), payload=payload)
    latency = time.perf_counter() - started
    assert result.byte_size == 86_400_044 and result.duration_seconds == 300
    assert 0.001 < result.peak <= 1
    final = output / "artifacts" / result.storage_key
    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=codec_name,sample_rate,channels,bits_per_raw_sample",
                "-of",
                "json",
                str(final),
            ],
            text=True,
        )
    )
    assert not list((output / "temp").rglob("*.wav*"))
    (output / "five-minute-result.json").write_text(
        json.dumps(
            {
                "result": asdict(result),
                "latencySeconds": latency,
                "ffprobe": probe,
            },
            indent=2,
        )
        + "\n"
    )
    failures = []
    async with httpx.AsyncClient(trust_env=False, timeout=20) as http:

        def request(job_id: UUID, maximum: int, timeout: int = 120000) -> dict:
            return {
                "requestVersion": "render-service-request.v1",
                "requestId": str(job_id),
                "outputStorageKey": f"jobs/{job_id}/render.wav",
                "maximumBytes": maximum,
                "timeoutMs": timeout,
                "bridgeRequest": {
                    "requestVersion": "render-bridge-request.v1",
                    "requestId": str(job_id),
                    "outputToken": "0" * 32,
                    "outputBitDepth": 24,
                    "graph": graph,
                },
            }

        phase("low-budget")
        response = await http.post(
            origin + "/v1/render", json=request(UUID(int=1903), 64 * 1024**2)
        )
        assert response.status_code == 400
        assert response.json()["errorCode"] == "RENDER_OUTPUT_BUDGET_EXCEEDED"
        try:
            await client.render(
                job_id=UUID(int=1904),
                payload=payload.model_copy(update={"maximum_output_bytes": 64 * 1024**2}),
            )
        except ChromiumRenderError as exc:
            assert exc.code == "RENDER_OUTPUT_BUDGET_EXCEEDED" and not exc.retryable
        else:
            raise AssertionError("underfunded payload accepted")
        failures.append(
            {
                "case": "legacy-64MiB-five-minutes",
                "http": 400,
                "errorCode": "RENDER_OUTPUT_BUDGET_EXCEEDED",
            }
        )
        phase("timeout")
        response = await http.post(
            origin + "/v1/render", json=request(UUID(int=1905), 86_400_044, 1000)
        )
        (output / "timeout-response.json").write_text(
            json.dumps(
                {
                    "status": response.status_code,
                    "body": response.json(),
                }
            )
        )
        assert response.status_code == 504 and response.json()["errorCode"] == "RENDER_TIMEOUT"
        failures.append(
            {"case": "actual-executor-timeout", "http": 504, "errorCode": "RENDER_TIMEOUT"}
        )
        phase("cancel")
        task = asyncio.create_task(client.render(job_id=UUID(int=1906), payload=payload))
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was lost")
        # Wait for the server's one slot to leave the interrupted render; malformed
        # requests return 400 only after that slot is free. No new render is queued.
        for _ in range(60):
            response = await http.post(origin + "/v1/render", json={})
            if response.status_code == 400:
                break
            assert response.status_code == 429
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("cancelled executor did not release slot")
        assert not list((output / "temp").rglob("*.wav*"))
        failures.append(
            {
                "case": "actual-client-cancel",
                "cancelledErrorPreserved": True,
                "slotReleased": True,
                "temporaryFiles": 0,
            }
        )
    phase("complete")
    report = {
        "schemaVersion": "p1a-render-capacity-evidence.v1",
        "date": "2026-10-19",
        "graphTracks": len(graph["tracks"]),
        "graphEvents": sum(len(t.get("notes", t.get("triggers", []))) for t in graph["tracks"]),
        "fiveMinuteLatencySeconds": latency,
        "fiveMinuteResult": asdict(result),
        "ffprobe": probe,
        "failures": failures,
        "remainingTemporaryMedia": 0,
        "dbUiReopenMeasured": False,
        "pinnedDockerWorkerMeasured": False,
        "subjectiveAudioQualityMeasured": False,
    }
    (output / "client-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps({"phase": "complete", "seconds": latency, "bytes": result.byte_size}), flush=True
    )


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2]))
