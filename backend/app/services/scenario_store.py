"""Persistence of scenario definitions and immutable snapshots.

ScenarioDefinition ──persist──▶ MySQL master/planning rows ──load──▶ ScenarioDefinition ──build──▶ snapshot
The round trip is tested to be lossless so DB-backed runs and in-memory benchmark runs are identical.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.optimization.common.contracts import ObjectiveWeights, ScenarioParams, ScenarioSnapshot
from app.schemas.scenario_def import (
    CustomerDef,
    DockDef,
    DowntimeDef,
    EquipmentDef,
    FacilityDef,
    OrderDef,
    OrderLineDef,
    PackStationDef,
    ScenarioDefinition,
    SkuDef,
    TaskModelParams,
    TravelParams,
    VehicleDef,
    WorkerDef,
)
from app.services.snapshot_builder import build_snapshot


def _local_to_utc(tz: ZoneInfo, day, local_min: int) -> datetime:  # type: ignore[no-untyped-def]
    return (datetime.combine(day, time(0, 0)) + timedelta(minutes=local_min)).replace(tzinfo=tz).astimezone(UTC)


def _utc_to_local(tz: ZoneInfo, day, at: datetime) -> int:  # type: ignore[no-untyped-def]
    local = at.astimezone(tz).replace(tzinfo=None)
    return int((local - datetime.combine(day, time(0, 0))).total_seconds() // 60)


def _get_or_create(db: Session, model, where: dict, values: dict):  # type: ignore[no-untyped-def]
    row = db.scalar(select(model).filter_by(**where))
    if row is None:
        row = model(**where, **values)
        db.add(row)
        db.flush()
    else:
        for k, v in values.items():
            setattr(row, k, v)
    return row


def persist_definition(db: Session, d: ScenarioDefinition, user_id: int | None = None) -> m.Scenario:
    """Upsert master data by code and create a new Scenario that references the definition's orders."""
    f = d.facility
    fac = _get_or_create(
        db,
        m.Facility,
        {"code": f.code},
        {"name": f.name, "timezone": f.timezone, "x_km": f.x_km, "y_km": f.y_km, "lat": f.lat, "lon": f.lon},
    )
    tz = ZoneInfo(f.timezone)
    cust = {}
    for c in d.customers:
        cust[c.code] = _get_or_create(
            db,
            m.Customer,
            {"facility_id": fac.id, "code": c.code},
            {
                "name": c.name,
                "x_km": c.x_km,
                "y_km": c.y_km,
                "lat": c.lat,
                "lon": c.lon,
                "service_min": c.service_min,
                "tw_start_local_min": c.tw_start_local,
                "tw_end_local_min": c.tw_end_local,
            },
        )
    skus = {}
    for s in d.skus:
        skus[s.code] = _get_or_create(
            db,
            m.Sku,
            {"facility_id": fac.id, "code": s.code},
            {
                "name": s.name,
                "zone": s.zone,
                "unit_weight_g": s.unit_weight_g,
                "unit_volume_ml": s.unit_volume_ml,
                "pick_sec_per_unit": s.pick_sec_per_unit,
            },
        )
    for code, qty in d.inventory.items():
        _get_or_create(db, m.InventoryBalance, {"facility_id": fac.id, "sku_id": skus[code].id}, {"on_hand": qty})
    for w in d.workers:
        _get_or_create(
            db,
            m.Worker,
            {"facility_id": fac.id, "code": w.code},
            {"name": w.name, "skills": sorted(w.skills), "hourly_cost": Decimal(str(w.hourly_cost)), "active": True},
        )
    for e in d.equipment:
        _get_or_create(
            db,
            m.Equipment,
            {"facility_id": fac.id, "code": e.code},
            {"name": e.name or e.code, "kind": e.kind, "active": True},
        )
    for p in d.pack_stations:
        _get_or_create(
            db, m.PackStation, {"facility_id": fac.id, "code": p.code}, {"name": p.name or p.code, "active": True}
        )
    for k in d.docks:
        _get_or_create(
            db,
            m.Dock,
            {"facility_id": fac.id, "code": k.code},
            {"name": k.name or k.code, "vehicle_classes": sorted(k.vehicle_classes), "active": True},
        )
    for v in d.vehicles:
        _get_or_create(
            db,
            m.Vehicle,
            {"facility_id": fac.id, "code": v.code},
            {
                "vehicle_class": v.vehicle_class,
                "capacity_kg": v.capacity_kg,
                "capacity_l": v.capacity_l,
                "fixed_cost": Decimal(str(v.fixed_cost)),
                "cost_per_km": Decimal(str(v.cost_per_km)),
                "status": v.status,
            },
        )

    # calendars are replaced wholesale for the facility (they are master data, not history)
    for row in db.scalars(select(m.ResourceCalendar).where(m.ResourceCalendar.facility_id == fac.id)):
        db.delete(row)
    db.flush()
    cal = []
    cal += [
        ("worker", w.code, "shift", w.shift_start_local, w.shift_end_local, w.regular_end_local, None)
        for w in d.workers
    ]
    cal += [
        ("pack_station", p.code, "shift", p.open_start_local, p.open_end_local, None, None) for p in d.pack_stations
    ]
    cal += [("dock", k.code, "shift", k.open_start_local, k.open_end_local, None, None) for k in d.docks]
    cal += [("vehicle", v.code, "shift", v.shift_start_local, v.shift_end_local, None, None) for v in d.vehicles]
    cal += [
        (t.resource_type, t.resource_code, "downtime", t.start_local, t.end_local, None, t.reason) for t in d.downtimes
    ]
    for rt, code, kind, s, e, reg, reason in cal:
        db.add(
            m.ResourceCalendar(
                facility_id=fac.id,
                resource_type=rt,
                resource_code=code,
                kind=kind,
                start_local_min=s,
                end_local_min=e,
                regular_end_local_min=reg,
                reason=reason,
            )
        )

    sc = m.Scenario(
        facility_id=fac.id,
        name=d.name,
        description=d.description,
        operating_date=d.operating_date,
        horizon_start_local_min=d.horizon_start_local,
        horizon_min=d.horizon_min,
        seed=d.seed,
        params=d.params.model_dump(),
        weights=d.weights.model_dump(),
        task_model=d.task_model.model_dump(),
        travel_params=d.travel.model_dump(),
        status="READY",
        created_by=user_id,
    )
    db.add(sc)
    db.flush()
    for o in d.orders:
        row = db.scalar(select(m.Order).where(m.Order.facility_id == fac.id, m.Order.code == o.code))
        if row is None:
            row = m.Order(
                facility_id=fac.id,
                code=o.code,
                customer_id=cust[o.customer_code].id,
                release_at=_local_to_utc(tz, d.operating_date, o.release_local),
                due_at=_local_to_utc(tz, d.operating_date, o.due_local),
                priority=o.priority,
                status=o.status,
                lines=[m.OrderLine(sku_id=skus[ln.sku_code].id, qty=ln.qty) for ln in o.lines],
            )
            db.add(row)
            db.flush()
        db.add(m.ScenarioOrder(scenario_id=sc.id, order_id=row.id))
    db.flush()
    return sc


def load_definition(db: Session, sc: m.Scenario) -> ScenarioDefinition:
    fac = db.get(m.Facility, sc.facility_id)
    assert fac is not None
    tz = ZoneInfo(fac.timezone)
    day = sc.operating_date
    orders = list(
        db.scalars(
            select(m.Order)
            .join(m.ScenarioOrder, m.ScenarioOrder.order_id == m.Order.id)
            .where(m.ScenarioOrder.scenario_id == sc.id)
            .order_by(m.Order.code)
        )
    )
    cust_rows = {c.id: c for c in db.scalars(select(m.Customer).where(m.Customer.facility_id == fac.id))}
    sku_rows = {s.id: s for s in db.scalars(select(m.Sku).where(m.Sku.facility_id == fac.id))}
    inv = {
        sku_rows[i.sku_id].code: i.on_hand
        for i in db.scalars(select(m.InventoryBalance).where(m.InventoryBalance.facility_id == fac.id))
    }
    cal = list(db.scalars(select(m.ResourceCalendar).where(m.ResourceCalendar.facility_id == fac.id)))
    shift = {(c.resource_type, c.resource_code): c for c in cal if c.kind == "shift"}
    used_cust = sorted({o.customer_id for o in orders})

    def sh(rt: str, code: str, default: tuple[int, int]) -> tuple[int, int, int | None]:
        c = shift.get((rt, code))
        return (c.start_local_min, c.end_local_min, c.regular_end_local_min) if c else (*default, None)

    workers = []
    for w in db.scalars(
        select(m.Worker).where(m.Worker.facility_id == fac.id, m.Worker.active.is_(True)).order_by(m.Worker.code)
    ):
        s, e, reg = sh("worker", w.code, (sc.horizon_start_local_min, sc.horizon_start_local_min + sc.horizon_min))
        workers.append(
            WorkerDef(
                code=w.code,
                name=w.name,
                skills=list(w.skills),
                hourly_cost=float(w.hourly_cost),
                shift_start_local=s,
                shift_end_local=e,
                regular_end_local=reg,
            )
        )
    stations = []
    for p in db.scalars(
        select(m.PackStation)
        .where(m.PackStation.facility_id == fac.id, m.PackStation.active.is_(True))
        .order_by(m.PackStation.code)
    ):
        s, e, _ = sh("pack_station", p.code, (0, 2880))
        stations.append(PackStationDef(code=p.code, name=p.name, open_start_local=s, open_end_local=e))
    docks = []
    for k in db.scalars(
        select(m.Dock).where(m.Dock.facility_id == fac.id, m.Dock.active.is_(True)).order_by(m.Dock.code)
    ):
        s, e, _ = sh("dock", k.code, (0, 2880))
        docks.append(
            DockDef(
                code=k.code, name=k.name, vehicle_classes=list(k.vehicle_classes), open_start_local=s, open_end_local=e
            )
        )
    vehicles = []
    for v in db.scalars(select(m.Vehicle).where(m.Vehicle.facility_id == fac.id).order_by(m.Vehicle.code)):
        s, e, _ = sh("vehicle", v.code, (0, 2880))
        vehicles.append(
            VehicleDef(
                code=v.code,
                vehicle_class=v.vehicle_class,
                capacity_kg=v.capacity_kg,
                capacity_l=v.capacity_l,
                fixed_cost=float(v.fixed_cost),
                cost_per_km=float(v.cost_per_km),
                shift_start_local=s,
                shift_end_local=e,
                status=v.status,
            )
        )
    return ScenarioDefinition(
        name=sc.name,
        description=sc.description,
        seed=sc.seed,
        operating_date=day,
        horizon_start_local=sc.horizon_start_local_min,
        horizon_min=sc.horizon_min,
        facility=FacilityDef(
            code=fac.code, name=fac.name, timezone=fac.timezone, x_km=fac.x_km, y_km=fac.y_km, lat=fac.lat, lon=fac.lon
        ),
        customers=[
            CustomerDef(
                code=c.code,
                name=c.name,
                x_km=c.x_km,
                y_km=c.y_km,
                lat=c.lat,
                lon=c.lon,
                service_min=c.service_min,
                tw_start_local=c.tw_start_local_min,
                tw_end_local=c.tw_end_local_min,
            )
            for c in sorted((cust_rows[i] for i in used_cust), key=lambda c: c.code)
        ],
        skus=[
            SkuDef(
                code=s.code,
                name=s.name,
                zone=s.zone,
                unit_weight_g=s.unit_weight_g,
                unit_volume_ml=s.unit_volume_ml,
                pick_sec_per_unit=s.pick_sec_per_unit,
            )
            for s in sorted(sku_rows.values(), key=lambda s: s.code)
        ],
        inventory=inv,
        orders=[
            OrderDef(
                code=o.code,
                customer_code=cust_rows[o.customer_id].code,
                release_local=_utc_to_local(tz, day, o.release_at),
                due_local=_utc_to_local(tz, day, o.due_at),
                priority=o.priority,
                status=o.status,
                lines=[OrderLineDef(sku_code=sku_rows[ln.sku_id].code, qty=ln.qty) for ln in o.lines],
            )
            for o in orders
        ],
        workers=workers,
        equipment=[
            EquipmentDef(code=e.code, kind=e.kind, name=e.name)
            for e in db.scalars(
                select(m.Equipment)
                .where(m.Equipment.facility_id == fac.id, m.Equipment.active.is_(True))
                .order_by(m.Equipment.code)
            )
        ],
        pack_stations=stations,
        docks=docks,
        vehicles=vehicles,
        downtimes=[
            DowntimeDef(
                resource_type=c.resource_type,
                resource_code=c.resource_code,
                start_local=c.start_local_min,
                end_local=c.end_local_min,
                reason=c.reason or "",
            )
            for c in sorted(cal, key=lambda c: c.id)
            if c.kind == "downtime"
        ],
        params=ScenarioParams(**sc.params),
        weights=ObjectiveWeights(**sc.weights),
        task_model=TaskModelParams(**sc.task_model),
        travel=TravelParams(**sc.travel_params),
    )


def snapshot_hash(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def _persist_matrix(db: Session, facility_id: int, snap: ScenarioSnapshot) -> int:
    tmx = snap.travel
    row = db.scalar(
        select(m.TravelMatrixRow).where(
            m.TravelMatrixRow.facility_id == facility_id, m.TravelMatrixRow.version == tmx.version
        )
    )
    if row is not None:
        return row.id
    row = m.TravelMatrixRow(
        facility_id=facility_id,
        version=tmx.version,
        provenance=tmx.provenance,
        symmetric=tmx.symmetric,
        params={"notes": tmx.notes},
    )
    db.add(row)
    db.flush()
    ids = tmx.location_ids
    db.bulk_insert_mappings(
        m.TravelMatrixEntry,
        [  # type: ignore[arg-type]
            {
                "matrix_id": row.id,
                "from_loc": a,
                "to_loc": b,
                "distance_m": tmx.distance_m[i][j],
                "duration_min": tmx.duration_min[i][j],
            }
            for i, a in enumerate(ids)
            for j, b in enumerate(ids)
            if i != j
        ],
    )
    return row.id


def store_snapshot(db: Session, sc: m.Scenario, snap: ScenarioSnapshot, reason: str) -> m.ScenarioSnapshotRow:
    """Persist a snapshot (deduplicated by content hash against the latest version)."""
    latest = db.scalar(
        select(m.ScenarioSnapshotRow)
        .where(m.ScenarioSnapshotRow.scenario_id == sc.id)
        .order_by(m.ScenarioSnapshotRow.version.desc())
        .limit(1)
    )
    version = (latest.version + 1) if latest else 1
    snap = snap.model_copy(update={"scenario_id": str(sc.id), "snapshot_version": version})
    content = snap.model_dump(mode="json")
    h = snapshot_hash({k: v for k, v in content.items() if k != "snapshot_version"})
    if latest is not None and latest.content_hash == h:
        return latest
    row = m.ScenarioSnapshotRow(scenario_id=sc.id, version=version, content=content, content_hash=h, reason=reason)
    db.add(row)
    db.flush()
    db.bulk_insert_mappings(
        m.TaskRow,
        [  # type: ignore[arg-type]
            {
                "snapshot_id": row.id,
                "task_code": t.id,
                "order_code": t.order_id,
                "task_type": t.type,
                "duration_min": t.duration_min,
                "release_min": t.release_min,
                "requirements": [r.model_dump() for r in t.requirements],
            }
            for t in snap.tasks
        ],
    )
    db.bulk_insert_mappings(
        m.TaskDependency,
        [  # type: ignore[arg-type]
            {"snapshot_id": row.id, "task_code": t.id, "predecessor_code": p}
            for t in snap.tasks
            for p in t.predecessors
        ],
    )
    mx = _persist_matrix(db, sc.facility_id, snap)
    if sc.travel_matrix_id != mx:
        sc.travel_matrix_id = mx
    db.flush()
    return row


def current_snapshot(db: Session, sc: m.Scenario, reason: str = "run") -> m.ScenarioSnapshotRow:
    """Snapshot of the scenario's *current* master data (re-uses the latest row if unchanged)."""
    snap = build_snapshot(load_definition(db, sc), scenario_id=str(sc.id))
    return store_snapshot(db, sc, snap, reason)


def snapshot_from_row(row: m.ScenarioSnapshotRow) -> ScenarioSnapshot:
    return ScenarioSnapshot.model_validate(row.content)


def snapshot_count(db: Session, scenario_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(m.ScenarioSnapshotRow)
            .where(m.ScenarioSnapshotRow.scenario_id == scenario_id)
        )
        or 0
    )
