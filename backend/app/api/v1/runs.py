"""Optimization runs: enqueue (202), poll, schedule, validation, metrics, cancel, compare; algorithm catalog."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, WriterUser
from app.api.errors import ApiError
from app.api.ratelimit import check_rate
from app.api.v1.scenarios import get_scenario
from app.db import models as m
from app.optimization.common import registry
from app.optimization.common.contracts import ScheduleMetrics, UnservedOrder, ValidationReport
from app.schemas.api import (
    AlgorithmOut,
    CompareOut,
    CompareRow,
    MetricsOut,
    OrderInfo,
    Page,
    ResourceLane,
    RunCreate,
    RunOut,
    ScheduleOut,
    VehicleInfo,
)
from app.services.audit import audit
from app.services.runs import RunError, enqueue_run, load_schedule, request_cancel
from app.services.scenario_store import current_snapshot, snapshot_from_row

router = APIRouter(tags=["runs"])

KPI_KEYS = (
    "on_time_rate",
    "total_lateness_min",
    "orders_served",
    "orders_unserved",
    "warehouse_makespan_min",
    "end_to_end_makespan_min",
    "total_distance_km",
    "vehicles_used",
    "overtime_min",
    "changed_tasks",
    "changed_routes",
    "stability_score",
    "avg_utilization",
)


def get_run(db, run_id: int) -> m.ScheduleRun:  # type: ignore[no-untyped-def]
    r = db.get(m.ScheduleRun, run_id)
    if r is None:
        raise ApiError(404, "not_found", f"run {run_id} not found")
    return r


def run_out(db, r: m.ScheduleRun) -> RunOut:  # type: ignore[no-untyped-def]
    snap_row = db.get(m.ScenarioSnapshotRow, r.snapshot_id)
    sc = db.get(m.Scenario, r.scenario_id)
    content = snap_row.content
    kpis = None
    if r.metrics:
        kpis = {k: r.metrics.get(k) for k in KPI_KEYS}
        kpis["cost"] = r.metrics.get("cost")
    vs = None
    if r.validation:
        vs = {
            "is_feasible": r.validation["is_feasible"],
            "scope": r.validation["scope"],
            **(r.validation.get("stats") or {}),
        }
    md = dict(r.solver_metadata or {})
    md.pop("traceback", None)
    return RunOut(
        id=r.id,
        scenario_id=r.scenario_id,
        scenario_name=sc.name,
        snapshot_id=r.snapshot_id,
        snapshot_version=snap_row.version,
        parent_run_id=r.parent_run_id,
        schedule_version=r.schedule_version,
        problem_type=r.problem_type,
        algorithm=r.algorithm,
        params=r.params or {},
        seed=r.seed,
        time_limit_s=r.time_limit_s,
        status=r.status,
        solver_status=r.solver_status,
        progress=r.progress,
        cancel_requested=r.cancel_requested,
        queued_at=r.queued_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        runtime_ms=r.runtime_ms,
        is_feasible=r.is_feasible,
        objective_total=float(r.objective_total) if r.objective_total is not None else None,
        error_message=r.error_message,
        kpis=kpis,
        validation_summary=vs,
        solver_metadata=md,
        horizon_start=content["horizon_start"],
        timezone=content["timezone"],
    )


@router.get("/algorithms", response_model=list[AlgorithmOut])
def algorithms(_: CurrentUser) -> list[AlgorithmOut]:
    return [
        AlgorithmOut(
            name=a.name,
            problem_types=list(a.problem_types),
            kind=a.kind,
            description=a.description,
            available=a.available,
            stochastic=a.stochastic,
            phase=a.phase,
        )
        for a in registry.all_algorithms()
    ]


@router.post("/scenarios/{scenario_id}/runs", response_model=RunOut, status_code=202)
def create_run(scenario_id: int, body: RunCreate, db: DbSession, user: WriterUser) -> RunOut:
    sc = get_scenario(db, scenario_id)
    check_rate(user.id, "run")
    try:
        run = enqueue_run(
            db,
            sc,
            body.problem_type,
            body.algorithm,
            body.time_limit_s,
            body.seed,
            body.params,
            user.id,
            dispatch=False,
        )
    except RunError as e:
        raise ApiError(422, e.code, str(e)) from e
    audit(db, user.id, "enqueue", "run", str(run.id), detail={"algorithm": body.algorithm})
    db.commit()
    from app.services.runs import dispatch_run

    dispatch_run(run.id)
    db.refresh(run)
    return run_out(db, run)


class ExperimentCreate(BaseModel):
    problem_type: Literal["warehouse", "dock", "routing", "integrated"]
    algorithms: list[str] = Field(min_length=1, max_length=12)
    seeds: list[int] = Field(default=[0], min_length=1, max_length=20)
    time_limit_s: float = Field(default=5.0, gt=0, le=120)
    params: dict[str, Any] = Field(default_factory=dict)


class ExperimentOut(BaseModel):
    scenario_id: int
    snapshot_id: int
    run_ids: list[int]
    note: str


@router.post("/scenarios/{scenario_id}/experiments", response_model=ExperimentOut, status_code=202)
def create_experiment(scenario_id: int, body: ExperimentCreate, db: DbSession, user: WriterUser) -> ExperimentOut:
    """Enqueue algorithms × seeds on ONE shared snapshot so results are directly comparable."""
    sc = get_scenario(db, scenario_id)
    check_rate(user.id, "experiment")
    if len(body.algorithms) * len(body.seeds) > 60:
        raise ApiError(422, "experiment_too_large", "at most 60 runs per experiment")
    snap_row = current_snapshot(db, sc, reason="experiment")
    db.commit()
    ids = []
    for alg in body.algorithms:
        try:
            info = registry.get(alg)
        except KeyError as e:
            raise ApiError(422, "unknown_algorithm", f"Unknown algorithm '{alg}'") from e
        for seed in body.seeds if info.stochastic else body.seeds[:1]:
            try:
                run = enqueue_run(
                    db,
                    sc,
                    body.problem_type,
                    alg,
                    body.time_limit_s,
                    seed,
                    body.params,
                    user.id,
                    snapshot_row=snap_row,
                    dispatch=False,
                )
            except RunError as e:
                raise ApiError(422, e.code, str(e)) from e
            ids.append(run.id)
    audit(db, user.id, "experiment", "scenario", str(sc.id), detail={"runs": ids, "algorithms": body.algorithms})
    db.commit()
    from app.services.runs import dispatch_run

    for rid in ids:
        dispatch_run(rid)
    return ExperimentOut(
        scenario_id=sc.id,
        snapshot_id=snap_row.id,
        run_ids=ids,
        note="deterministic algorithms run once; stochastic ones once per seed",
    )


@router.get("/runs", response_model=Page[RunOut])
def list_runs(
    db: DbSession,
    _: CurrentUser,
    scenario_id: int | None = None,
    status: str | None = None,
    algorithm: str | None = None,
    problem_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[RunOut]:
    stmt = select(m.ScheduleRun)
    if scenario_id is not None:
        stmt = stmt.where(m.ScheduleRun.scenario_id == scenario_id)
    if status:
        stmt = stmt.where(m.ScheduleRun.status == status)
    if algorithm:
        stmt = stmt.where(m.ScheduleRun.algorithm == algorithm)
    if problem_type:
        stmt = stmt.where(m.ScheduleRun.problem_type == problem_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.ScheduleRun.id.desc()).limit(limit).offset(offset))
    return Page(items=[run_out(db, r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_one(run_id: int, db: DbSession, _: CurrentUser) -> RunOut:
    return run_out(db, get_run(db, run_id))


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel(run_id: int, db: DbSession, user: WriterUser) -> RunOut:
    r = get_run(db, run_id)
    if r.status not in ("QUEUED", "RUNNING"):
        raise ApiError(409, "not_cancellable", f"run is {r.status}")
    r = request_cancel(db, r)
    audit(db, user.id, "cancel", "run", str(run_id))
    db.commit()
    return run_out(db, r)


@router.get("/runs/{run_id}/schedule", response_model=ScheduleOut)
def schedule(run_id: int, db: DbSession, _: CurrentUser) -> ScheduleOut:
    r = get_run(db, run_id)
    if r.status != "SUCCEEDED":
        raise ApiError(
            409,
            "no_schedule",
            f"run is {r.status}; only validated (SUCCEEDED) runs publish schedules",
            {"error_message": r.error_message},
        )
    snap = snapshot_from_row(db.get(m.ScenarioSnapshotRow, r.snapshot_id))
    assigns, routes = load_schedule(db, r)
    cmap = snap.customer_map()
    unserved = [
        UnservedOrder(order_id=s.order_code, reason=s.unserved_reason or "", penalty=float(s.penalty or 0))
        for s in db.scalars(select(m.Shipment).where(m.Shipment.run_id == r.id, m.Shipment.status == "UNSERVED"))
    ]
    return ScheduleOut(
        run_id=r.id,
        status=r.status,
        problem_type=r.problem_type,
        algorithm=r.algorithm,
        horizon_start=snap.horizon_start,
        horizon_min=snap.horizon_min,
        timezone=snap.timezone,
        current_time_min=snap.current_time_min,
        assignments=assigns,
        routes=routes,
        unserved=unserved,
        resources=[
            ResourceLane(
                id=x.id,
                kind=x.kind,
                name=x.name,
                available=x.available,
                skills=x.skills,
                regular_end=x.regular_end,
                vehicle_classes=x.vehicle_classes,
            )
            for x in snap.resources
        ],
        vehicles=[
            VehicleInfo(
                id=v.id,
                vehicle_class=v.vehicle_class,
                capacity_kg=v.capacity_kg,
                capacity_l=v.capacity_l,
                shift_start=v.shift_start,
                shift_end=v.shift_end,
                available=v.available,
            )
            for v in snap.vehicles
        ],
        orders=[
            OrderInfo(
                id=o.id,
                customer_id=o.customer_id,
                release_min=o.release_min,
                due_min=o.due_min,
                priority=o.priority,
                weight_kg=o.weight_kg,
                tw_start=cmap[o.customer_id].tw_start,
                tw_end=cmap[o.customer_id].tw_end,
            )
            for o in snap.orders
        ],
        travel_provenance=snap.travel.provenance,
        geometry_note=(
            "경로선은 정류장 간 직선(schematic)이며 실제 도로 경로가 아닙니다. 거리·시간은 합성 유클리드 행렬 기준."
        ),
    )


@router.get("/runs/{run_id}/validation", response_model=ValidationReport)
def validation(run_id: int, db: DbSession, _: CurrentUser) -> ValidationReport:
    r = get_run(db, run_id)
    if not r.validation:
        raise ApiError(409, "no_validation", f"run is {r.status}; no validation report yet")
    return ValidationReport.model_validate(r.validation)


@router.get("/runs/{run_id}/metrics", response_model=MetricsOut)
def metrics(run_id: int, db: DbSession, _: CurrentUser) -> MetricsOut:
    r = get_run(db, run_id)
    md: dict[str, Any] = r.solver_metadata or {}
    exact = r.algorithm.endswith("cpsat") or "ortools" in str(md.get("solver", ""))
    return MetricsOut(
        run_id=r.id,
        algorithm=r.algorithm,
        metrics=ScheduleMetrics.model_validate(r.metrics) if r.metrics else None,
        solver_status=r.solver_status,
        solver_objective=md.get("solver_objective"),
        best_bound=md.get("best_bound"),
        gap=md.get("gap") if exact else None,
        gap_note=(
            "gap = |solver objective − best bound| / objective, on the solver's internal objective "
            "(not the shared evaluator total)"
            if exact and md.get("best_bound") is not None
            else "no optimality gap: heuristic/metaheuristic results carry no lower bound"
        ),
    )


@router.get("/runs/{run_id}/compare", response_model=CompareOut)
def compare(
    run_id: int,
    db: DbSession,
    _: CurrentUser,
    ids: str | None = Query(
        default=None, description="comma-separated run ids; default: all runs of the same scenario & snapshot"
    ),
) -> CompareOut:
    base = get_run(db, run_id)
    if ids:
        try:
            wanted = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError as e:
            raise ApiError(422, "invalid_ids", "ids must be integers") from e
        runs = [get_run(db, i) for i in dict.fromkeys([run_id, *wanted])]
    else:
        runs = list(
            db.scalars(
                select(m.ScheduleRun)
                .where(m.ScheduleRun.scenario_id == base.scenario_id, m.ScheduleRun.snapshot_id == base.snapshot_id)
                .order_by(m.ScheduleRun.id)
            )
        )
    if any(r.scenario_id != base.scenario_id for r in runs):
        raise ApiError(422, "different_scenarios", "compare only runs of the same scenario")
    rows = []
    for r in runs:
        mt = r.metrics or {}
        rows.append(
            CompareRow(
                run_id=r.id,
                algorithm=r.algorithm,
                problem_type=r.problem_type,
                status=r.status,
                solver_status=r.solver_status,
                is_feasible=r.is_feasible,
                seed=r.seed,
                runtime_ms=r.runtime_ms,
                total_cost=float(r.objective_total) if r.objective_total is not None else None,
                cost=mt.get("cost"),
                on_time_rate=mt.get("on_time_rate"),
                total_lateness_min=mt.get("total_lateness_min"),
                total_distance_km=mt.get("total_distance_km"),
                vehicles_used=mt.get("vehicles_used"),
                orders_unserved=mt.get("orders_unserved"),
                warehouse_makespan_min=mt.get("warehouse_makespan_min"),
                end_to_end_makespan_min=mt.get("end_to_end_makespan_min"),
                avg_utilization=mt.get("avg_utilization"),
                changed_tasks=mt.get("changed_tasks"),
                stability_score=mt.get("stability_score"),
                gap=(r.solver_metadata or {}).get("gap"),
            )
        )
    snaps = sorted({r.snapshot_id for r in runs})
    return CompareOut(
        scenario_id=base.scenario_id,
        snapshot_ids=snaps,
        same_snapshot=len(snaps) == 1,
        objective_note="total_cost는 모든 알고리즘에 동일한 공통 평가기로 계산됩니다(솔버 내부 목적값 아님).",
        rows=rows,
    )
