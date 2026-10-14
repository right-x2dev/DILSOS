"""Celery task definitions (thin wrappers — all logic lives in app.services.runs)."""

from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="dilsos.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="dilsos.execute_run", acks_late=True)
def execute_run_task(run_id: int) -> str:
    from app.services.runs import execute_run

    return execute_run(run_id)
