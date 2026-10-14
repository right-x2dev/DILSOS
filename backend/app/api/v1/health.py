from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    status: Literal["ok"]


class DependencyCheck(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    task_backend: str
    database_dialect: str
    checks: list[DependencyCheck]


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse(status="ok")


def _check_db() -> DependencyCheck:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return DependencyCheck(name="database", ok=True)
    except Exception as e:  # noqa: BLE001 - report, never raise from health
        return DependencyCheck(name="database", ok=False, detail=type(e).__name__)


def _check_redis(url: str) -> DependencyCheck:
    try:
        import redis

        redis.Redis.from_url(url, socket_connect_timeout=1).ping()
        return DependencyCheck(name="redis", ok=True)
    except Exception as e:  # noqa: BLE001
        return DependencyCheck(name="redis", ok=False, detail=type(e).__name__)


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
def ready() -> JSONResponse:
    s = get_settings()
    checks = [_check_db()]
    if s.task_backend == "celery":
        checks.append(_check_redis(s.redis_url))
    ok = all(c.ok for c in checks)
    body = ReadyResponse(
        status="ready" if ok else "not_ready",
        task_backend=s.task_backend,
        database_dialect=get_engine().dialect.name,
        checks=checks,
    )
    return JSONResponse(status_code=200 if ok else 503, content=body.model_dump())
