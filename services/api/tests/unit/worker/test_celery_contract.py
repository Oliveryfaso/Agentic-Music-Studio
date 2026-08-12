from __future__ import annotations

from motif_forge.config import Settings
from motif_forge.worker.celery_app import create_celery_app


def test_celery_uses_late_ack_single_prefetch_and_no_result_backend() -> None:
    app = create_celery_app(Settings(environment="test", redis_url="redis://localhost:6379/0"))

    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_ignore_result is True
    assert app.conf.result_backend is None
    assert app.conf.task_default_queue == "media"
