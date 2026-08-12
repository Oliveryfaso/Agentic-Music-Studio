"""Celery task entrypoints carrying only persisted Job identifiers."""

from __future__ import annotations

import asyncio
import os
import socket
from uuid import UUID

from motif_forge.config import get_settings
from motif_forge.worker.celery_app import celery_app
from motif_forge.worker.execution import execute_media_job


@celery_app.task(
    bind=True,
    name="motif_forge.execute_media_job",
    acks_late=True,
    ignore_result=True,
    reject_on_worker_lost=True,
)  # type: ignore[untyped-decorator]
def execute_media_job_task(self: object, job_id: str) -> dict[str, str | None]:
    del self
    parsed_job_id = UUID(job_id)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    result = asyncio.run(
        execute_media_job(parsed_job_id, settings=get_settings(), worker_id=worker_id)
    )
    return {
        "job_id": str(result.job_id),
        "status": result.status,
        "artifact_id": str(result.artifact_id) if result.artifact_id else None,
        "error_code": result.error_code,
    }
