"""Celery task definitions."""

from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="dilsos.ping")
def ping() -> str:
    return "pong"
