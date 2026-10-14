"""Run lifecycle: QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED.

* The HTTP handler only enqueues (202); solving happens in a worker (Celery / DB-poller / eager tests).
* A worker claims a run with an atomic conditional UPDATE, so two workers can never run the same job.
* Outputs are published in ONE transaction and only if the independent validator says feasible;
  otherwise the run is FAILED with the validation report attached (never a fake SUCCEEDED).
"""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import get_settings
from app.db import models as m
from app.db.session import get_sessionmaker
from app.optimization.common import registry
from app.optimization.common.contracts import (
    CancellationToken,
    RouteStop,
    ScheduleResult,
    SolveConfig,
    TaskAssignment,
    VehicleRoute,
)
from app.optimization.common.runner import is_publishable, run_algorithm
from app.services.scenario_store import current_snapshot, snapshot_from_row

log = logging.getLogger("dilsos.runs")


class RunError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def enqueue_run(
    db: Session,
    scenario: m.Scenario,
    problem_type: str,
    algorithm: str,
    time_limit_s: float,
    seed: int,
    params: dict[str, Any],
    user_id: int | None,
    snapshot_row: m.ScenarioSnapshotRow | None = None,
    parent_run_id: int | None = None,
    schedule_version: int = 1,
    dispatch: bool = True,
) -> m.ScheduleRun:
    s = get_settings()
    try:
        info = registry.get(algorithm)
    except KeyError as e:
        raise RunError("unknown_algorithm", f"Unknown algorithm '{algorithm}'") from e
    if problem_type not in info.problem_types:
        raise RunError("unsupported_problem", f"{algorithm} supports {list(info.problem_types)}, not {problem_type}")
    if not info.available:
        raise RunError("solver_unavailable", f"{algorithm} requires {list(info.requires)}")
    if time_limit_s > s.max_solver_time_limit_s:
        raise RunError("time_limit_too_large", f"time_limit_s must be <= {s.max_solver_time_limit_s}")
    snap_row = snapshot_row or current_snapshot(db, scenario, reason="run")
    run = m.ScheduleRun(
        scenario_id=scenario.id,
        snapshot_id=snap_row.id,
        problem_type=problem_type,
        algorithm=algorithm,
        params=params,
        seed=seed,
        time_limit_s=time_limit_s,
        status="QUEUED",
        created_by=user_id,
        parent_run_id=parent_run_id,
        schedule_version=schedule_version,
    )
    db.add(run)
    db.commit()
    if dispatch:
        dispatch_run(run.id)
    return run


def dispatch_run(run_id: int) -> None:
    backend = get_settings().task_backend
    if backend == "eager":
        execute_run(run_id, worker_id="eager")
    elif backend == "celery":
        from app.tasks.jobs import execute_run_task

        execute_run_task.delay(run_id)
    # "db": the persistent DB-polling worker will claim it


def claim_run(db: Session, run_id: int, worker_id: str) -> bool:
    res = db.execute(
        update(m.ScheduleRun)
        .where(m.ScheduleRun.id == run_id, m.ScheduleRun.status == "QUEUED")
        .values(
            status="RUNNING",
            started_at=datetime.now(UTC),
            worker_id=worker_id,
            progress=5,
            lock_version=m.ScheduleRun.lock_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return res.rowcount == 1  # type: ignore[attr-defined]


def claim_next(db: Session, worker_id: str) -> int | None:
    for rid in db.scalars(
        select(m.ScheduleRun.id)
        .where(m.ScheduleRun.status == "QUEUED")
        .order_by(m.ScheduleRun.queued_at, m.ScheduleRun.id)
        .limit(5)
    ):
        if claim_run(db, rid, worker_id):
            return rid
    return None


def _cancel_checker(run_id: int):  # type: ignore[no-untyped-def]
    last = [0.0, False]

    def check() -> bool:
        now = time.monotonic()
        if now - last[0] < 0.5:
            return bool(last[1])
        last[0] = now
        with get_sessionmaker()() as s:
            last[1] = bool(s.scalar(select(m.ScheduleRun.cancel_requested).where(m.ScheduleRun.id == run_id)))
        return bool(last[1])

    return check


def execute_run(run_id: int, worker_id: str | None = None) -> str:
    """Claim (if QUEUED) and execute a run. Returns the final run status."""
    worker_id = worker_id or worker_identity()
    S = get_sessionmaker()
    with S() as db:
        run = db.get(m.ScheduleRun, run_id)
        if run is None:
            return "MISSING"
        if run.status == "QUEUED" and not claim_run(db, run_id, worker_id):
            return db.get(m.ScheduleRun, run_id).status  # type: ignore[union-attr]
        db.refresh(run)
        if run.status != "RUNNING" or run.worker_id != worker_id:
            return run.status
        snap = snapshot_from_row(db.get(m.ScenarioSnapshotRow, run.snapshot_id))  # type: ignore[arg-type]
        cfg = SolveConfig(
            problem_type=run.problem_type,
            time_limit_s=min(run.time_limit_s, get_settings().run_timeout_s),
            seed=run.seed,
            params=run.params or {},
        )  # type: ignore[arg-type]
        algorithm = run.algorithm
    cancel = CancellationToken(_cancel_checker(run_id))
    log.info("run start", extra={"run_id": run_id, "algorithm": algorithm})
    try:
        result = run_algorithm(snap, algorithm, cfg, run_id=str(run_id), cancel=cancel)
    except Exception as e:  # noqa: BLE001
        log.exception("run crashed", extra={"run_id": run_id})
        return _finish_failed(run_id, f"{type(e).__name__}: {e}")
    return publish_result(run_id, result, cancelled=cancel.cancelled)


def _finish_failed(run_id: int, message: str, status: str = "FAILED", extra: dict | None = None) -> str:
    values = {
        "status": status,
        "error_message": message[:4000],
        "finished_at": datetime.now(UTC),
        "progress": 100,
        "lock_version": m.ScheduleRun.lock_version + 1,
        **(extra or {}),
    }
    with get_sessionmaker()() as db:
        db.execute(
            update(m.ScheduleRun)
            .where(m.ScheduleRun.id == run_id, m.ScheduleRun.status.in_(("QUEUED", "RUNNING")))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return db.scalar(select(m.ScheduleRun.status).where(m.ScheduleRun.id == run_id)) or status


def publish_result(run_id: int, result: ScheduleResult, cancelled: bool = False) -> str:
    """Retries on optimistic-lock conflicts (e.g. a cancel request landing at the same moment)."""
    for attempt in range(3):
        try:
            return _publish(run_id, result, cancelled)
        except StaleDataError:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def _publish(run_id: int, result: ScheduleResult, cancelled: bool) -> str:
    common: dict[str, Any] = {
        "solver_status": result.status,
        "runtime_ms": result.runtime_ms,
        "solver_metadata": _jsonable(result.solver_metadata),
        "validation": result.validation.model_dump(mode="json") if result.validation else None,
        "metrics": result.metrics.model_dump(mode="json") if result.metrics else None,
        "is_feasible": bool(result.validation and result.validation.is_feasible),
        "objective_total": Decimal(str(result.metrics.cost.total_cost)) if result.metrics else None,
    }
    if cancelled:
        return _finish_failed(run_id, "cancelled by user", status="CANCELLED", extra=common)
    if result.status == "ERROR":
        return _finish_failed(run_id, str(result.solver_metadata.get("error", "solver error")), extra=common)
    if not is_publishable(result):
        n = len(result.validation.errors) if result.validation else 0
        reason = (
            f"schedule rejected: solver status {result.status}, {n} validation error(s)"
            if result.validation
            else "no validation report"
        )
        return _finish_failed(run_id, reason, extra=common)

    with get_sessionmaker()() as db, db.begin():
        run = db.get(m.ScheduleRun, run_id)
        assert run is not None
        if run.status != "RUNNING":  # cancelled/failed concurrently → do not publish
            return run.status
        for a in result.assignments:
            db.add(
                m.ScheduleAssignment(
                    run_id=run_id,
                    task_code=a.task_id,
                    task_type=a.task_type,
                    order_codes=a.order_ids,
                    resource_code=a.resource_id,
                    resources=a.resources,
                    start_min=a.start_min,
                    end_min=a.end_min,
                    frozen=a.frozen,
                )
            )
        delivered: dict[str, tuple[str, int, int]] = {}
        for r in result.routes:
            if not r.stops:
                continue
            rr = m.RouteRow(
                run_id=run_id,
                vehicle_code=r.vehicle_id,
                dock_code=r.dock_id,
                order_codes=r.order_ids,
                ready_min=r.ready_min,
                load_start_min=r.load_start_min,
                load_end_min=r.load_end_min,
                departure_min=r.departure_min,
                return_min=r.return_min,
                distance_m=r.distance_m,
                load_kg=r.load_kg,
                load_l=r.load_l,
                geometry=r.geometry,
            )
            db.add(rr)
            db.flush()
            for s in r.stops:
                db.add(
                    m.RouteStopRow(
                        route_id=rr.id,
                        seq=s.seq,
                        customer_code=s.customer_id,
                        location_code=s.location_id,
                        order_codes=s.order_ids,
                        arrival_min=s.arrival_min,
                        service_start_min=s.service_start_min,
                        service_end_min=s.service_end_min,
                        departure_min=s.departure_min,
                        wait_min=s.wait_min,
                        late_min=s.late_min,
                        load_after_kg=s.load_after_kg,
                        load_after_l=s.load_after_l,
                    )
                )
                for oid in s.order_ids:
                    delivered[oid] = (r.vehicle_id, s.service_start_min, s.late_min)
        pack_end: dict[str, int] = {}
        for a in result.assignments:
            if a.task_type != "LOAD":
                for oid in a.order_ids:
                    pack_end[oid] = max(pack_end.get(oid, 0), a.end_min)
        unserved = {u.order_id: u for u in result.unserved}
        snap_orders = {oid for oid in pack_end} | set(delivered) | set(unserved)
        for oid in sorted(snap_orders):
            if oid in unserved:
                db.add(
                    m.Shipment(
                        run_id=run_id,
                        order_code=oid,
                        status="UNSERVED",
                        unserved_reason=unserved[oid].reason,
                        penalty=Decimal(str(unserved[oid].penalty)),
                    )
                )
            else:
                veh, at, late = delivered.get(oid, (None, None, None))
                db.add(
                    m.Shipment(
                        run_id=run_id,
                        order_code=oid,
                        status="SERVED",
                        vehicle_code=veh,
                        ready_min=pack_end.get(oid),
                        delivered_min=at,
                        late_min=late,
                    )
                )
        for k, v in common.items():
            setattr(run, k, v)
        run.status = "SUCCEEDED"
        run.progress = 100
        run.finished_at = datetime.now(UTC)
    log.info("run published", extra={"run_id": run_id, "status": "SUCCEEDED", "duration_ms": result.runtime_ms})
    return "SUCCEEDED"


def request_cancel(db: Session, run: m.ScheduleRun) -> m.ScheduleRun:
    if run.status == "QUEUED":
        res = db.execute(
            update(m.ScheduleRun)
            .where(m.ScheduleRun.id == run.id, m.ScheduleRun.status == "QUEUED")
            .values(
                status="CANCELLED",
                cancel_requested=True,
                finished_at=datetime.now(UTC),
                error_message="cancelled before start",
                lock_version=m.ScheduleRun.lock_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if res.rowcount == 1:  # type: ignore[attr-defined]
            db.refresh(run)
            return run
    if run.status == "RUNNING":
        db.execute(
            update(m.ScheduleRun)
            .where(m.ScheduleRun.id == run.id)
            .values(cancel_requested=True, lock_version=m.ScheduleRun.lock_version + 1)
            .execution_options(synchronize_session=False)
        )
        db.commit()
    db.refresh(run)
    return run


def recover_stale_runs(db: Session) -> int:
    """Fail RUNNING runs whose worker vanished (older than 2× run timeout)."""
    cutoff = datetime.now(UTC) - timedelta(seconds=2 * get_settings().run_timeout_s + 60)
    res = db.execute(
        update(m.ScheduleRun)
        .where(m.ScheduleRun.status == "RUNNING", m.ScheduleRun.started_at < cutoff)
        .values(
            status="FAILED",
            error_message="worker lost (timeout exceeded)",
            finished_at=datetime.now(UTC),
            lock_version=m.ScheduleRun.lock_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(res.rowcount)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------------------
# read-back helpers (DB rows → contract objects)
# ---------------------------------------------------------------------------------------------
def load_schedule(db: Session, run: m.ScheduleRun) -> tuple[list[TaskAssignment], list[VehicleRoute]]:
    assigns = [
        TaskAssignment(
            task_id=a.task_code,
            task_type=a.task_type,
            order_ids=list(a.order_codes),  # type: ignore[arg-type]
            resource_id=a.resource_code,
            resources=dict(a.resources),
            start_min=a.start_min,
            end_min=a.end_min,
            frozen=a.frozen,
        )
        for a in db.scalars(
            select(m.ScheduleAssignment)
            .where(m.ScheduleAssignment.run_id == run.id)
            .order_by(m.ScheduleAssignment.start_min, m.ScheduleAssignment.task_code)
        )
    ]
    routes = []
    for r in db.scalars(select(m.RouteRow).where(m.RouteRow.run_id == run.id).order_by(m.RouteRow.vehicle_code)):
        stops = [
            RouteStop(
                seq=s.seq,
                customer_id=s.customer_code,
                location_id=s.location_code,
                order_ids=list(s.order_codes),
                arrival_min=s.arrival_min,
                service_start_min=s.service_start_min,
                service_end_min=s.service_end_min,
                departure_min=s.departure_min,
                wait_min=s.wait_min,
                late_min=s.late_min,
                load_after_kg=s.load_after_kg,
                load_after_l=s.load_after_l,
            )
            for s in db.scalars(
                select(m.RouteStopRow).where(m.RouteStopRow.route_id == r.id).order_by(m.RouteStopRow.seq)
            )
        ]
        routes.append(
            VehicleRoute(
                vehicle_id=r.vehicle_code,
                dock_id=r.dock_code,
                order_ids=list(r.order_codes),
                ready_min=r.ready_min,
                load_start_min=r.load_start_min,
                load_end_min=r.load_end_min,
                departure_min=r.departure_min,
                return_min=r.return_min,
                stops=stops,
                distance_m=r.distance_m,
                load_kg=r.load_kg,
                load_l=r.load_l,
                geometry=r.geometry,
            )
        )  # type: ignore[arg-type]
    return assigns, routes


def _jsonable(d: Any) -> Any:
    if isinstance(d, dict):
        return {str(k): _jsonable(v) for k, v in d.items()}
    if isinstance(d, list | tuple):
        return [_jsonable(x) for x in d]
    if isinstance(d, float) and (d != d or d in (float("inf"), float("-inf"))):
        return None
    return d
