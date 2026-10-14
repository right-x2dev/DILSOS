"""Operational metrics in Prometheus text format (run outcomes/durations from DB + in-process HTTP counters)."""

from __future__ import annotations

import threading
from collections import Counter

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.db import models as m

router = APIRouter(prefix="/ops", tags=["ops"])

_lock = threading.Lock()
HTTP: Counter[tuple[str, str]] = Counter()  # (method, status class) → count


def record_http(method: str, status: int) -> None:
    with _lock:
        HTTP[(method, f"{status // 100}xx")] += 1


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(db: DbSession) -> str:
    lines = [
        "# HELP dilsos_runs_total Optimization runs by status and algorithm.",
        "# TYPE dilsos_runs_total gauge",
    ]
    for status, alg, n in db.execute(
        select(m.ScheduleRun.status, m.ScheduleRun.algorithm, func.count()).group_by(
            m.ScheduleRun.status, m.ScheduleRun.algorithm
        )
    ).all():
        lines.append(f'dilsos_runs_total{{status="{status}",algorithm="{alg}"}} {n}')
    lines += ["# HELP dilsos_run_runtime_ms Solver runtime of finished runs.", "# TYPE dilsos_run_runtime_ms summary"]
    for alg, s, c, mx in db.execute(
        select(
            m.ScheduleRun.algorithm,
            func.sum(m.ScheduleRun.runtime_ms),
            func.count(m.ScheduleRun.runtime_ms),
            func.max(m.ScheduleRun.runtime_ms),
        )
        .where(m.ScheduleRun.runtime_ms.is_not(None))
        .group_by(m.ScheduleRun.algorithm)
    ).all():
        lines.append(f'dilsos_run_runtime_ms_sum{{algorithm="{alg}"}} {int(s or 0)}')
        lines.append(f'dilsos_run_runtime_ms_count{{algorithm="{alg}"}} {c}')
        lines.append(f'dilsos_run_runtime_ms_max{{algorithm="{alg}"}} {int(mx or 0)}')
    infeasible = db.scalar(select(func.count()).select_from(m.ScheduleRun).where(m.ScheduleRun.is_feasible.is_(False)))
    lines += [
        "# HELP dilsos_runs_rejected_infeasible Runs whose schedule failed validation (never published).",
        "# TYPE dilsos_runs_rejected_infeasible gauge",
        f"dilsos_runs_rejected_infeasible {infeasible or 0}",
    ]
    queued = db.scalar(select(func.count()).select_from(m.ScheduleRun).where(m.ScheduleRun.status == "QUEUED"))
    lines += ["# TYPE dilsos_queue_depth gauge", f"dilsos_queue_depth {queued or 0}"]
    lines += [
        "# HELP dilsos_http_requests_total HTTP requests served by this process.",
        "# TYPE dilsos_http_requests_total counter",
    ]
    with _lock:
        for (method, klass), n in sorted(HTTP.items()):
            lines.append(f'dilsos_http_requests_total{{method="{method}",status="{klass}"}} {n}')
    return "\n".join(lines) + "\n"
