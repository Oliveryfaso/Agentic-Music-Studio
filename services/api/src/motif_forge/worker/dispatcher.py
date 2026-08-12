"""Long-running Outbox dispatcher process."""

from __future__ import annotations

import asyncio
import os
import socket

from motif_forge.config import get_settings
from motif_forge.infrastructure.persistence.database import (
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.worker.celery_app import celery_app
from motif_forge.worker.outbox import CeleryMediaJobPublisher, PostgresOutboxStore, dispatch_once


async def run_dispatcher() -> None:
    settings = get_settings()
    if settings.postgres_dsn is None or settings.redis_url is None:
        raise RuntimeError("dispatcher requires PostgreSQL and Redis configuration")
    engine = create_postgres_engine(settings.postgres_dsn.get_secret_value())
    store = PostgresOutboxStore(create_session_factory(engine))
    publisher = CeleryMediaJobPublisher(celery_app, queue=settings.media_worker_queue)
    owner = f"{socket.gethostname()}:{os.getpid()}"
    try:
        while True:
            delivered = await dispatch_once(
                store,
                publisher,
                owner=owner,
                batch_size=settings.outbox_batch_size,
                lease_seconds=settings.outbox_lease_seconds,
            )
            if delivered == 0:
                await asyncio.sleep(settings.outbox_poll_interval_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_dispatcher())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
