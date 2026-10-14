"""Pure conversion ScenarioDefinition → ScenarioSnapshot (no DB access).

* Local wall-clock minutes → integer minutes from horizon start, via zoneinfo (DST-safe).
* Tasks: one PICK (worker [+ zone skill] [+ forklift if heavy]) and one PACK (packer + pack station)
  per order, PICK → PACK precedence.
* Availability: shift/opening window clipped to the horizon minus downtime intervals.
* Travel matrix: synthetic euclidean × circuity at a reference speed (provenance labelled).
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.optimization.common.contracts import (
    Customer,
    Interval,
    Location,
    Order,
    OrderLine,
    Resource,
    ResourceRequirement,
    ScenarioSnapshot,
    Sku,
    Task,
    TravelMatrix,
    Vehicle,
)
from app.schemas.scenario_def import ScenarioDefinition

DEPOT_ID = "DEPOT"


class Clock:
    """Converts local minutes-of-operating-day to snapshot minutes (and back)."""

    def __init__(self, timezone: str, operating_date: date, horizon_start_local: int):
        self.tz = ZoneInfo(timezone)
        self.midnight = datetime.combine(operating_date, time(0, 0))
        self.horizon_start = self.aware(horizon_start_local)

    @classmethod
    def of(cls, d: ScenarioDefinition) -> Clock:
        return cls(d.facility.timezone, d.operating_date, d.horizon_start_local)

    def aware(self, local_min: int) -> datetime:
        return (self.midnight + timedelta(minutes=local_min)).replace(tzinfo=self.tz)

    def rel(self, local_min: int) -> int:
        return int((self.aware(local_min) - self.horizon_start).total_seconds() // 60)


def subtract(windows: list[tuple[int, int]], blocks: list[tuple[int, int]]) -> list[Interval]:
    out = []
    for ws, we in windows:
        segs = [(ws, we)]
        for bs, be in sorted(blocks):
            nxt = []
            for s, e in segs:
                if be <= s or bs >= e:
                    nxt.append((s, e))
                    continue
                if s < bs:
                    nxt.append((s, bs))
                if be < e:
                    nxt.append((be, e))
            segs = nxt
        out.extend(Interval(start=s, end=e) for s, e in segs if e > s)
    return sorted(out, key=lambda i: i.start)


def euclid_matrix(locs: list[Location], circuity: float, speed_kmh: float) -> tuple[list[list[int]], list[list[int]]]:
    n = len(locs)
    dist = [[0] * n for _ in range(n)]
    dur = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            km = math.hypot(locs[i].x_km - locs[j].x_km, locs[i].y_km - locs[j].y_km) * circuity
            dist[i][j] = int(round(km * 1000))
            dur[i][j] = max(1, math.ceil(km / speed_kmh * 60))
    return dist, dur


def build_snapshot(d: ScenarioDefinition, scenario_id: str = "local", version: int = 1) -> ScenarioSnapshot:
    # canonical ordering so DB round-trips and generator output yield byte-identical snapshots
    d = d.model_copy(
        update={
            "workers": sorted(d.workers, key=lambda x: x.code),
            "pack_stations": sorted(d.pack_stations, key=lambda x: x.code),
            "equipment": sorted(d.equipment, key=lambda x: x.code),
            "docks": sorted(d.docks, key=lambda x: x.code),
            "vehicles": sorted(d.vehicles, key=lambda x: x.code),
            "customers": sorted(d.customers, key=lambda x: x.code),
            "skus": sorted(d.skus, key=lambda x: x.code),
        }
    )
    clk = Clock.of(d)
    H = d.horizon_min
    tm = d.task_model

    def clip(a: int, b: int) -> tuple[int, int]:
        return max(0, clk.rel(a)), min(H, clk.rel(b))

    down: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for dt in d.downtimes:
        down.setdefault((dt.resource_type, dt.resource_code), []).append(clip(dt.start_local, dt.end_local))

    depot = Location(id=DEPOT_ID, x_km=d.facility.x_km, y_km=d.facility.y_km, lat=d.facility.lat, lon=d.facility.lon)
    locs = [depot] + [Location(id=f"L-{c.code}", x_km=c.x_km, y_km=c.y_km, lat=c.lat, lon=c.lon) for c in d.customers]
    customers = [
        Customer(
            id=c.code,
            name=c.name,
            location_id=f"L-{c.code}",
            service_min=c.service_min,
            tw_start=clk.rel(c.tw_start_local),
            tw_end=clk.rel(c.tw_end_local),
        )
        for c in d.customers
    ]
    skus = {s.code: s for s in d.skus}
    resources: list[Resource] = []
    for w in d.workers:
        resources.append(
            Resource(
                id=w.code,
                kind="worker",
                name=w.name,
                skills=sorted(w.skills),
                hourly_cost=w.hourly_cost,
                available=subtract([clip(w.shift_start_local, w.shift_end_local)], down.get(("worker", w.code), [])),
                regular_end=clk.rel(w.regular_end_local) if w.regular_end_local is not None else None,
            )
        )
    for ps in d.pack_stations:
        resources.append(
            Resource(
                id=ps.code,
                kind="pack_station",
                name=ps.name or ps.code,
                available=subtract(
                    [clip(ps.open_start_local, ps.open_end_local)], down.get(("pack_station", ps.code), [])
                ),
            )
        )
    for eq in d.equipment:
        resources.append(
            Resource(
                id=eq.code,
                kind="equipment",
                name=eq.name or eq.code,
                skills=[eq.kind],
                available=subtract([(0, H)], down.get(("equipment", eq.code), [])),
            )
        )
    for dk in d.docks:
        resources.append(
            Resource(
                id=dk.code,
                kind="dock",
                name=dk.name or dk.code,
                vehicle_classes=sorted(dk.vehicle_classes),
                available=subtract([clip(dk.open_start_local, dk.open_end_local)], down.get(("dock", dk.code), [])),
            )
        )

    orders: list[Order] = []
    tasks: list[Task] = []
    workers = [w for w in d.workers]
    stations = [p.code for p in d.pack_stations]
    forklifts = [e.code for e in d.equipment if e.kind == "forklift"]
    for o in sorted(d.orders, key=lambda x: x.code):
        units = sum(ln.qty for ln in o.lines)
        wt_g = sum(ln.qty * skus[ln.sku_code].unit_weight_g for ln in o.lines)
        vol_ml = sum(ln.qty * skus[ln.sku_code].unit_volume_ml for ln in o.lines)
        weight_kg, volume_l = math.ceil(wt_g / 1000), math.ceil(vol_ml / 1000)
        rel = max(0, clk.rel(o.release_local))
        orders.append(
            Order(
                id=o.code,
                customer_id=o.customer_code,
                release_min=rel,
                due_min=clk.rel(o.due_local),
                priority=o.priority,
                lines=[OrderLine(sku_id=ln.sku_code, qty=ln.qty) for ln in o.lines],
                weight_kg=weight_kg,
                volume_l=volume_l,
                units=units,
            )
        )
        zones = sorted({skus[ln.sku_code].zone for ln in o.lines})
        need = {"pick"} | {tm.zone_skill[z] for z in zones if z in tm.zone_skill}
        pickers = [w.code for w in workers if need <= set(w.skills)]
        pick_sec = sum(ln.qty * skus[ln.sku_code].pick_sec_per_unit for ln in o.lines)
        pick_req = [ResourceRequirement(kind="worker", eligible_ids=pickers)]
        if weight_kg > tm.forklift_weight_kg:
            pick_req.append(ResourceRequirement(kind="equipment", eligible_ids=forklifts))
        tasks.append(
            Task(
                id=f"{o.code}-PICK",
                order_id=o.code,
                type="PICK",
                release_min=rel,
                requirements=pick_req,
                duration_min=tm.pick_base_min + len(zones) * 2 + math.ceil(pick_sec / 60),
            )
        )
        packers = [w.code for w in workers if "pack" in w.skills]
        tasks.append(
            Task(
                id=f"{o.code}-PACK",
                order_id=o.code,
                type="PACK",
                release_min=rel,
                requirements=[
                    ResourceRequirement(kind="worker", eligible_ids=packers),
                    ResourceRequirement(kind="pack_station", eligible_ids=stations),
                ],
                duration_min=tm.pack_base_min + math.ceil(units * tm.pack_sec_per_unit / 60),
                predecessors=[f"{o.code}-PICK"],
            )
        )

    vehicles = [
        Vehicle(
            id=v.code,
            vehicle_class=v.vehicle_class,
            capacity_kg=v.capacity_kg,
            capacity_l=v.capacity_l,
            fixed_cost=v.fixed_cost,
            cost_per_km=v.cost_per_km,
            shift_start=max(0, clk.rel(v.shift_start_local)),
            shift_end=min(H, clk.rel(v.shift_end_local)),
            depot_location_id=DEPOT_ID,
            available=v.status == "AVAILABLE",
        )
        for v in d.vehicles
    ]
    dist, dur = euclid_matrix(locs, d.travel.circuity, d.travel.speed_kmh)
    mat_hash = hashlib.sha256(json.dumps([dist, dur]).encode()).hexdigest()[:12]
    travel = TravelMatrix(
        version=f"{d.travel.provenance}-{mat_hash}",
        provenance="synthetic_euclidean",
        location_ids=[x.id for x in locs],
        distance_m=dist,
        duration_min=dur,
        symmetric=True,
        notes=f"SYNTHETIC: euclidean × {d.travel.circuity} at {d.travel.speed_kmh} km/h — not real road travel time",
    )
    return ScenarioSnapshot(
        scenario_id=scenario_id,
        snapshot_version=version,
        name=d.name,
        seed=d.seed,
        horizon_start=clk.horizon_start.astimezone(ZoneInfo("UTC")),
        horizon_min=H,
        timezone=d.facility.timezone,
        depot_location_id=DEPOT_ID,
        locations=locs,
        customers=customers,
        skus=[
            Sku(
                id=s.code,
                zone=s.zone,
                unit_weight_g=s.unit_weight_g,
                unit_volume_ml=s.unit_volume_ml,
                pick_sec_per_unit=s.pick_sec_per_unit,
            )
            for s in d.skus
        ],
        inventory=dict(d.inventory),
        orders=orders,
        tasks=tasks,
        resources=resources,
        vehicles=vehicles,
        travel=travel,
        params=d.params,
        weights=d.weights,
        cancelled_order_ids=sorted(o.code for o in d.orders if o.status == "CANCELLED"),
    )
