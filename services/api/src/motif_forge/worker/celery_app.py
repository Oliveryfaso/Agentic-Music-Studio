"""Celery transport configuration; PostgreSQL remains the Job truth source."""

from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from motif_forge.config import Settings, get_settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    active = settings or get_settings()
    broker_url = (
        active.redis_url.get_secret_value() if active.redis_url is not None else "memory://"
    )
    app = Celery(
        "motif_forge_media",
        broker=broker_url,
        include=["motif_forge.worker.tasks"],
    )
    app.conf.update(
        accept_content=["json"],
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": 900, "max_retries": 3},
        enable_utc=True,
        result_backend=None,
        task_acks_late=True,
        task_default_queue=active.media_worker_queue,
        task_ignore_result=True,
        task_reject_on_worker_lost=True,
        task_serializer="json",
        task_soft_time_limit=active.media_worker_soft_time_limit_seconds,
        task_time_limit=active.media_worker_hard_time_limit_seconds,
        timezone="UTC",
        worker_cancel_long_running_tasks_on_connection_loss=True,
        worker_prefetch_multiplier=1,
    )
    return app


celery_app = create_celery_app()
