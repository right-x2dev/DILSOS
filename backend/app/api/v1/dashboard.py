"""Overview dashboard aggregates — every number comes from DB rows / stored run metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.v1.runs import run_out
from app.api.v1.scenarios import get_scenario
from app.db import models as m
from app.schemas.api import RunOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardOut(BaseModel):
    scenario_id: int
    scenario_name: str
    orders_by_status: dict[str, int]
    orders_by_priority: dict[str, int]
    resources: dict[str, int]
    vehicles_by_status: dict[str, int]
    runs_by_status: dict[str, int]
    latest_runs: list[RunOut]
    latest_success: RunOut | None
    kpi_source: str
    recent_events: list[dict[str, Any]]


@router.get("/summary", response_model=DashboardOut)
def summary(scenario_id: int, db: DbSession, _: CurrentUser) -> DashboardOut:
    sc = get_scenario(db, scenario_id)
    order_q = (
        select(m.Order)
        .join(m.ScenarioOrder, m.ScenarioOrder.order_id == m.Order.id)
        .where(m.ScenarioOrder.scenario_id == sc.id)
        .subquery()
    )
    by_status = dict(db.execute(select(order_q.c.status, func.count()).group_by(order_q.c.status)).all())
    by_prio = {
        str(k): v for k, v in db.execute(select(order_q.c.priority, func.count()).group_by(order_q.c.priority)).all()
    }

    def cnt(model) -> int:  # type: ignore[no-untyped-def]
        return int(db.scalar(select(func.count()).select_from(model).where(model.facility_id == sc.facility_id)) or 0)

    veh = dict(
        db.execute(
            select(m.Vehicle.status, func.count())
            .where(m.Vehicle.facility_id == sc.facility_id)
            .group_by(m.Vehicle.status)
        ).all()
    )
    runs_status = dict(
        db.execute(
            select(m.ScheduleRun.status, func.count())
            .where(m.ScheduleRun.scenario_id == sc.id)
            .group_by(m.ScheduleRun.status)
        ).all()
    )
    latest = list(
        db.scalars(
            select(m.ScheduleRun).where(m.ScheduleRun.scenario_id == sc.id).order_by(m.ScheduleRun.id.desc()).limit(8)
        )
    )
    succ = db.scalar(
        select(m.ScheduleRun)
        .where(m.ScheduleRun.scenario_id == sc.id, m.ScheduleRun.status == "SUCCEEDED")
        .order_by(m.ScheduleRun.id.desc())
        .limit(1)
    )
    events = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "event_time_min": e.event_time_min,
            "affected": e.affected_code,
            "created_at": e.created_at.isoformat(),
        }
        for e in db.scalars(
            select(m.DisruptionEvent)
            .where(m.DisruptionEvent.scenario_id == sc.id)
            .order_by(m.DisruptionEvent.id.desc())
            .limit(5)
        )
    ]
    return DashboardOut(
        scenario_id=sc.id,
        scenario_name=sc.name,
        orders_by_status=by_status,
        orders_by_priority=by_prio,
        resources={
            "workers": cnt(m.Worker),
            "pack_stations": cnt(m.PackStation),
            "docks": cnt(m.Dock),
            "equipment": cnt(m.Equipment),
            "vehicles": cnt(m.Vehicle),
        },
        vehicles_by_status=veh,
        runs_by_status=runs_status,
        latest_runs=[run_out(db, r) for r in latest],
        latest_success=run_out(db, succ) if succ else None,
        kpi_source=(
            f"run #{succ.id} ({succ.algorithm}, {succ.problem_type})"
            if succ
            else "아직 성공한 실행이 없습니다 — KPI 없음"
        ),
        recent_events=events,
    )
