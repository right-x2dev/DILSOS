"""Facilities, orders and resources (workers / vehicles / docks)."""

from __future__ import annotations

import math
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, WriterUser
from app.api.errors import ApiError
from app.db import models as m
from app.schemas.api import (
    DockIn,
    DockOut,
    FacilityOut,
    OrderCreate,
    OrderLineOut,
    OrderOut,
    Page,
    VehicleIn,
    VehicleOut,
    WorkerIn,
    WorkerOut,
)
from app.services.audit import audit

router = APIRouter(tags=["master-data"])


def _facility(db, facility_id: int) -> m.Facility:  # type: ignore[no-untyped-def]
    f = db.get(m.Facility, facility_id)
    if f is None:
        raise ApiError(404, "not_found", f"facility {facility_id} not found")
    return f


@router.get("/facilities", response_model=list[FacilityOut])
def list_facilities(db: DbSession, _: CurrentUser) -> list[FacilityOut]:
    return [
        FacilityOut(id=f.id, code=f.code, name=f.name, timezone=f.timezone)
        for f in db.scalars(select(m.Facility).order_by(m.Facility.code))
    ]


def _order_out(o: m.Order, fac: m.Facility, cust: m.Customer, skus: dict[int, m.Sku]) -> OrderOut:
    grams = sum(ln.qty * skus[ln.sku_id].unit_weight_g for ln in o.lines)
    return OrderOut(
        id=o.id,
        code=o.code,
        facility_code=fac.code,
        customer_code=cust.code,
        customer_name=cust.name,
        release_at=o.release_at,
        due_at=o.due_at,
        priority=o.priority,
        status=o.status,
        units=sum(ln.qty for ln in o.lines),
        weight_kg=math.ceil(grams / 1000),
        lines=[OrderLineOut(sku_code=skus[ln.sku_id].code, qty=ln.qty) for ln in o.lines],
    )


@router.get("/orders", response_model=Page[OrderOut])
def list_orders(
    db: DbSession,
    _: CurrentUser,
    scenario_id: int | None = None,
    facility_id: int | None = None,
    status: str | None = Query(default=None, pattern="^(OPEN|CANCELLED|SHIPPED)$"),
    priority: int | None = Query(default=None, ge=1, le=3),
    q: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Page[OrderOut]:
    stmt = select(m.Order)
    if scenario_id is not None:
        stmt = stmt.join(m.ScenarioOrder, m.ScenarioOrder.order_id == m.Order.id).where(
            m.ScenarioOrder.scenario_id == scenario_id
        )
    if facility_id is not None:
        stmt = stmt.where(m.Order.facility_id == facility_id)
    if status:
        stmt = stmt.where(m.Order.status == status)
    if priority:
        stmt = stmt.where(m.Order.priority == priority)
    if q:
        cust_ids = select(m.Customer.id).where(m.Customer.code.like(f"%{q}%"))
        stmt = stmt.where(or_(m.Order.code.like(f"%{q}%"), m.Order.customer_id.in_(cust_ids)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.options(selectinload(m.Order.lines)).order_by(m.Order.due_at, m.Order.code).limit(limit).offset(offset)
        )
    )
    facs = {f.id: f for f in db.scalars(select(m.Facility))}
    custs = {c.id: c for c in db.scalars(select(m.Customer).where(m.Customer.id.in_({o.customer_id for o in rows})))}
    sku_ids = {ln.sku_id for o in rows for ln in o.lines}
    skus = {s.id: s for s in db.scalars(select(m.Sku).where(m.Sku.id.in_(sku_ids)))}
    return Page(
        items=[_order_out(o, facs[o.facility_id], custs[o.customer_id], skus) for o in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def create_order_row(db, body: OrderCreate, user_id: int | None) -> m.Order:  # type: ignore[no-untyped-def]
    sc = db.get(m.Scenario, body.scenario_id)
    if sc is None:
        raise ApiError(404, "not_found", f"scenario {body.scenario_id} not found")
    cust = db.scalar(
        select(m.Customer).where(m.Customer.facility_id == sc.facility_id, m.Customer.code == body.customer_code)
    )
    if cust is None:
        raise ApiError(422, "unknown_customer", f"customer {body.customer_code} not in facility")
    skus = {
        s.code: s
        for s in db.scalars(
            select(m.Sku).where(m.Sku.facility_id == sc.facility_id, m.Sku.code.in_([ln.sku_code for ln in body.lines]))
        )
    }
    missing = sorted({ln.sku_code for ln in body.lines} - set(skus))
    if missing:
        raise ApiError(422, "unknown_sku", f"unknown SKU(s): {', '.join(missing)}")
    if db.scalar(select(m.Order.id).where(m.Order.facility_id == sc.facility_id, m.Order.code == body.code)):
        raise ApiError(409, "duplicate_order", f"order code {body.code} already exists")
    o = m.Order(
        facility_id=sc.facility_id,
        code=body.code,
        customer_id=cust.id,
        release_at=body.release_at,
        due_at=body.due_at,
        priority=body.priority,
        status="OPEN",
        lines=[m.OrderLine(sku_id=skus[ln.sku_code].id, qty=ln.qty) for ln in body.lines],
    )
    db.add(o)
    db.flush()
    db.add(m.ScenarioOrder(scenario_id=sc.id, order_id=o.id))
    audit(db, user_id, "create", "order", o.code, detail={"scenario_id": sc.id})
    return o


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(body: OrderCreate, db: DbSession, user: WriterUser) -> OrderOut:
    try:
        o = create_order_row(db, body, user.id)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ApiError(409, "conflict", "order violates a uniqueness/foreign-key constraint") from e
    db.refresh(o)
    fac = db.get(m.Facility, o.facility_id)
    cust = db.get(m.Customer, o.customer_id)
    skus = {s.id: s for s in db.scalars(select(m.Sku).where(m.Sku.id.in_([ln.sku_id for ln in o.lines])))}
    return _order_out(o, fac, cust, skus)  # type: ignore[arg-type]


# ---------------- resources ----------------
def _shift(db, facility_id: int, rtype: str, code: str) -> m.ResourceCalendar | None:  # type: ignore[no-untyped-def]
    return db.scalar(
        select(m.ResourceCalendar).where(
            m.ResourceCalendar.facility_id == facility_id,
            m.ResourceCalendar.resource_type == rtype,
            m.ResourceCalendar.resource_code == code,
            m.ResourceCalendar.kind == "shift",
        )
    )


def _check_window(start: int, end: int) -> None:
    if end <= start:
        raise ApiError(422, "invalid_window", "end must be after start (use >1440 for overnight)")


@router.get("/resources/workers", response_model=list[WorkerOut])
def list_workers(db: DbSession, _: CurrentUser, facility_id: int) -> list[WorkerOut]:
    out = []
    for w in db.scalars(select(m.Worker).where(m.Worker.facility_id == facility_id).order_by(m.Worker.code)):
        c = _shift(db, facility_id, "worker", w.code)
        out.append(
            WorkerOut(
                id=w.id,
                facility_id=facility_id,
                code=w.code,
                name=w.name,
                skills=w.skills,
                hourly_cost=float(w.hourly_cost),
                active=w.active,
                shift_start_local_min=c.start_local_min if c else 0,
                shift_end_local_min=c.end_local_min if c else 0,
                regular_end_local_min=c.regular_end_local_min if c else None,
            )
        )
    return out


def _dup(db, model, facility_id: int, code: str) -> None:  # type: ignore[no-untyped-def]
    if db.scalar(select(model.id).where(model.facility_id == facility_id, model.code == code)):
        raise ApiError(409, "duplicate_code", f"{code} already exists in facility")


@router.post("/resources/workers", response_model=WorkerOut, status_code=201)
def create_worker(body: WorkerIn, db: DbSession, user: WriterUser) -> WorkerOut:
    _facility(db, body.facility_id)
    _check_window(body.shift_start_local_min, body.shift_end_local_min)
    _dup(db, m.Worker, body.facility_id, body.code)
    w = m.Worker(
        facility_id=body.facility_id,
        code=body.code,
        name=body.name,
        skills=sorted(set(body.skills)),
        hourly_cost=Decimal(str(body.hourly_cost)),
        active=True,
    )
    db.add(w)
    db.add(
        m.ResourceCalendar(
            facility_id=body.facility_id,
            resource_type="worker",
            resource_code=body.code,
            kind="shift",
            start_local_min=body.shift_start_local_min,
            end_local_min=body.shift_end_local_min,
            regular_end_local_min=body.regular_end_local_min,
        )
    )
    audit(db, user.id, "create", "worker", body.code)
    db.commit()
    return WorkerOut(id=w.id, active=True, **body.model_dump())


@router.get("/resources/vehicles", response_model=list[VehicleOut])
def list_vehicles(db: DbSession, _: CurrentUser, facility_id: int) -> list[VehicleOut]:
    out = []
    for v in db.scalars(select(m.Vehicle).where(m.Vehicle.facility_id == facility_id).order_by(m.Vehicle.code)):
        c = _shift(db, facility_id, "vehicle", v.code)
        out.append(
            VehicleOut(
                id=v.id,
                facility_id=facility_id,
                code=v.code,
                vehicle_class=v.vehicle_class,  # type: ignore[arg-type]
                capacity_kg=v.capacity_kg,
                capacity_l=v.capacity_l,
                fixed_cost=float(v.fixed_cost),
                cost_per_km=float(v.cost_per_km),
                status=v.status,  # type: ignore[arg-type]
                shift_start_local_min=c.start_local_min if c else 0,
                shift_end_local_min=c.end_local_min if c else 0,
            )
        )
    return out


@router.post("/resources/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(body: VehicleIn, db: DbSession, user: WriterUser) -> VehicleOut:
    _facility(db, body.facility_id)
    _check_window(body.shift_start_local_min, body.shift_end_local_min)
    _dup(db, m.Vehicle, body.facility_id, body.code)
    v = m.Vehicle(
        facility_id=body.facility_id,
        code=body.code,
        vehicle_class=body.vehicle_class,
        capacity_kg=body.capacity_kg,
        capacity_l=body.capacity_l,
        fixed_cost=Decimal(str(body.fixed_cost)),
        cost_per_km=Decimal(str(body.cost_per_km)),
        status=body.status,
    )
    db.add(v)
    db.add(
        m.ResourceCalendar(
            facility_id=body.facility_id,
            resource_type="vehicle",
            resource_code=body.code,
            kind="shift",
            start_local_min=body.shift_start_local_min,
            end_local_min=body.shift_end_local_min,
        )
    )
    audit(db, user.id, "create", "vehicle", body.code)
    db.commit()
    return VehicleOut(id=v.id, **body.model_dump())


@router.get("/resources/docks", response_model=list[DockOut])
def list_docks(db: DbSession, _: CurrentUser, facility_id: int) -> list[DockOut]:
    out = []
    for k in db.scalars(select(m.Dock).where(m.Dock.facility_id == facility_id).order_by(m.Dock.code)):
        c = _shift(db, facility_id, "dock", k.code)
        out.append(
            DockOut(
                id=k.id,
                facility_id=facility_id,
                code=k.code,
                name=k.name,
                vehicle_classes=k.vehicle_classes,
                active=k.active,
                open_start_local_min=c.start_local_min if c else 0,
                open_end_local_min=c.end_local_min if c else 0,
            )
        )
    return out


@router.post("/resources/docks", response_model=DockOut, status_code=201)
def create_dock(body: DockIn, db: DbSession, user: WriterUser) -> DockOut:
    _facility(db, body.facility_id)
    _check_window(body.open_start_local_min, body.open_end_local_min)
    _dup(db, m.Dock, body.facility_id, body.code)
    k = m.Dock(
        facility_id=body.facility_id,
        code=body.code,
        name=body.name,
        vehicle_classes=sorted(set(body.vehicle_classes)),
        active=True,
    )
    db.add(k)
    db.add(
        m.ResourceCalendar(
            facility_id=body.facility_id,
            resource_type="dock",
            resource_code=body.code,
            kind="shift",
            start_local_min=body.open_start_local_min,
            end_local_min=body.open_end_local_min,
        )
    )
    audit(db, user.id, "create", "dock", body.code)
    db.commit()
    return DockOut(id=k.id, active=True, **body.model_dump())
