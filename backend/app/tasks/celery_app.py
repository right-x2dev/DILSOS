"""Celery application (TASK_BACKEND=celery). Broker/result backend: Redis.

Run state is persisted in MySQL (`schedule_runs`); Celery only transports run IDs.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_s = get_settings()

celery_app = Celery("dilsos", broker=_s.redis_url, backend=_s.redis_url, include=["app.tasks.jobs"])
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=_s.run_timeout_s + 30,
    task_soft_time_limit=_s.run_timeout_s,
    task_always_eager=_s.task_backend == "eager",
    timezone="UTC",
    enable_utc=True,
)
app = celery_app
