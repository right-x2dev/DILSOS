"""Disruption events (idempotent) and versioned rescheduling (KEEP / PARTIAL / FULL)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, WriterUser
from app.api.errors import ApiError
from app.api.ratelimit import check_rate
from app.api.v1.runs import get_run
from app.api.v1.scenarios import get_scenario
from app.db import models as m
from app.optimization.rescheduling.events import EVENT_TYPES, DisruptionSpec
from app.services.audit import audit
from app.services.rescheduling import EventConflict, record_event, start_reschedules, summarize
from app.services.runs import RunError, dispatch_run

router = APIRouter(tags=["disruptions"])

AFFECTED_TYPE = {
    "worker_absence": "worker",
    "pack_station_outage": "pack_station",
    "dock_outage": "dock",
    "vehicle_breakdown": "vehicle",
    "order_cancellation": "order",
    "urgent_order": "order",
    "travel_time_increase": None,
}


class EventIn(BaseModel):
    event_type: Literal[EVENT_TYPES]  # type: ignore[valid-type]
    event_time_min: int = Field(ge=0, le=2880, description="minutes from the scenario horizon start")
    affected_code: str | None = Field(default=None, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=80)


class EventOut(BaseModel):
    id: int
    scenario_id: int
    idempotency_key: str
    event_type: str
    event_time_min: int
    affected_type: str | None
    affected_code: str | None
    payload: dict[str, Any]
    created_at: datetime


def _out(e: m.DisruptionEvent) -> EventOut:
    return EventOut(
        id=e.id,
        scenario_id=e.scenario_id,
        idempotency_key=e.idempotency_key,
        event_type=e.event_type,
        event_time_min=e.event_time_min,
        affected_type=e.affected_type,
        affected_code=e.affected_code,
        payload=e.payload,
        created_at=e.created_at,
    )


@router.post(
    "/scenarios/{scenario_id}/events",
    response_model=EventOut,
    status_code=201,
    responses={200: {"model": EventOut, "description": "idempotent replay"}},
)
def create_event(
    scenario_id: int,
    body: EventIn,
    db: DbSession,
    user: WriterUser,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EventOut:
    sc = get_scenario(db, scenario_id)
    key = (idempotency_key or body.idempotency_key or uuid.uuid4().hex)[:80]
    if body.event_type != "travel_time_increase" and body.event_type != "urgent_order" and not body.affected_code:
        raise ApiError(422, "missing_affected", f"{body.event_type} requires affected_code")
    if body.event_type == "travel_time_increase" and float(body.payload.get("factor", 1.3)) < 1:
        raise ApiError(422, "invalid_payload", "factor must be ≥ 1")
    spec = DisruptionSpec(
        event_type=body.event_type, time_min=body.event_time_min, affected_id=body.affected_code, payload=body.payload
    )
    try:
        ev, created = record_event(db, sc, key, spec, AFFECTED_TYPE[body.event_type], user.id)
    except EventConflict as e:
        raise ApiError(409, "idempotency_conflict", str(e)) from e
    if created:
        audit(
            db,
            user.id,
            "event",
            "scenario",
            str(sc.id),
            after_ref=f"event:{ev.id}",
            detail={"event_type": ev.event_type},
        )
    else:
        response.status_code = 200
    db.commit()
    return _out(ev)


@router.get("/scenarios/{scenario_id}/events", response_model=list[EventOut])
def list_events(scenario_id: int, db: DbSession, _: CurrentUser) -> list[EventOut]:
    get_scenario(db, scenario_id)
    return [
        _out(e)
        for e in db.scalars(
            select(m.DisruptionEvent)
            .where(m.DisruptionEvent.scenario_id == scenario_id)
            .order_by(m.DisruptionEvent.event_time_min, m.DisruptionEvent.id)
        )
    ]


class RescheduleIn(BaseModel):
    event_id: int
    policies: list[Literal["KEEP", "PARTIAL", "FULL"]] = Field(default=["KEEP", "PARTIAL", "FULL"], min_length=1)
    reoptimizer: str | None = Field(default=None, max_length=64)
    time_limit_s: float = Field(default=10.0, gt=0, le=120)
    seed: int = Field(default=0, ge=0)
    freeze_window_min: int = Field(default=30, ge=0, le=480)
    expected_schedule_version: int | None = Field(default=None, description="optimistic concurrency guard")


class RescheduleStarted(BaseModel):
    base_run_id: int
    event_id: int
    reschedule_ids: list[int]
    new_run_ids: list[int]


@router.post("/runs/{run_id}/reschedule", response_model=RescheduleStarted, status_code=202)
def reschedule(run_id: int, body: RescheduleIn, db: DbSession, user: WriterUser) -> RescheduleStarted:
    base = get_run(db, run_id)
    check_rate(user.id, "reschedule")
    if body.expected_schedule_version is not None and body.expected_schedule_version != base.schedule_version:
        raise ApiError(409, "version_conflict", "base schedule version changed", {"current": base.schedule_version})
    ev = db.get(m.DisruptionEvent, body.event_id)
    if ev is None:
        raise ApiError(404, "not_found", f"event {body.event_id} not found")
    if body.reoptimizer:
        from app.optimization.common import registry

        try:
            info = registry.get(body.reoptimizer)
        except KeyError as e:
            raise ApiError(422, "unknown_algorithm", f"unknown re-optimiser {body.reoptimizer}") from e
        if base.problem_type not in info.problem_types or body.reoptimizer.startswith("reschedule_"):
            raise ApiError(422, "unsupported_problem", f"{body.reoptimizer} cannot re-optimise {base.problem_type}")
    try:
        rrs = start_reschedules(
            db,
            base,
            ev,
            list(dict.fromkeys(body.policies)),
            body.reoptimizer,
            body.time_limit_s,
            body.seed,
            body.freeze_window_min,
            user.id,
        )
    except RunError as e:
        raise ApiError(422, e.code, str(e)) from e
    audit(
        db,
        user.id,
        "reschedule",
        "run",
        str(base.id),
        before_ref=f"run:{base.id}",
        after_ref=",".join(f"run:{r.new_run_id}" for r in rrs),
        detail={"event_id": ev.id, "policies": body.policies},
    )
    db.commit()
    for rr in rrs:
        run = db.get(m.ScheduleRun, rr.new_run_id)
        if run is not None and run.status == "QUEUED":
            dispatch_run(run.id)
    return RescheduleStarted(
        base_run_id=base.id,
        event_id=ev.id,
        reschedule_ids=[r.id for r in rrs],
        new_run_ids=[r.new_run_id for r in rrs if r.new_run_id],
    )


class RescheduleSummary(BaseModel):
    base_run_id: int
    items: list[dict[str, Any]]
    recommendations: dict[str, dict[str, Any]]


@router.get("/runs/{run_id}/reschedules", response_model=RescheduleSummary)
def reschedules(
    run_id: int,
    db: DbSession,
    _: CurrentUser,
    w_cost: float = 1.0,
    w_lateness: float = 0.5,
    w_changes: float = 0.5,
    w_runtime: float = 0.05,
) -> RescheduleSummary:
    get_run(db, run_id)
    return RescheduleSummary(
        **summarize(db, run_id, {"cost": w_cost, "lateness": w_lateness, "changes": w_changes, "runtime": w_runtime})
    )
