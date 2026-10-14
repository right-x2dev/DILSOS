"""Disruption events applied to an immutable snapshot (never to executed history).

MVP modelling choices (also shown in the UI):
* No preemption: an absence/outage that starts while a task or loading is in progress takes effect
  when that task finishes.
* Vehicle breakdown after loading started / departure is NOT modelled as mid-route recovery: the
  route stays as executed and the case is reported as an explicit exception.
* Travel-time increase applies to every movement that has not started (executed routes are frozen).
* Order cancellation after picking started keeps the executed work as history (reported).
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.optimization.common.contracts import Interval, ScenarioSnapshot, ScheduleResult
from app.optimization.common.tasks import make_order

EventType = Literal[
    "urgent_order",
    "worker_absence",
    "pack_station_outage",
    "dock_outage",
    "vehicle_breakdown",
    "travel_time_increase",
    "order_cancellation",
]

EVENT_TYPES: tuple[str, ...] = EventType.__args__  # type: ignore[attr-defined]


class DisruptionSpec(BaseModel):
    event_type: EventType
    time_min: int = Field(ge=0)
    affected_id: str | None = None
    payload: dict[str, Any] = {}


class AppliedEvent(BaseModel):
    snapshot: ScenarioSnapshot
    exceptions: list[str] = []
    affected_resources: list[str] = []
    affected_orders: list[str] = []
    affected_vehicles: list[str] = []
    timing_changed: bool = False


def _cut(windows: list[Interval], start: int, end: int) -> list[Interval]:
    out: list[Interval] = []
    for w in windows:
        if end <= w.start or start >= w.end:
            out.append(w)
            continue
        if w.start < start:
            out.append(Interval(start=w.start, end=start))
        if end < w.end:
            out.append(Interval(start=end, end=w.end))
    return out


def _busy_until(base: ScheduleResult, rid: str, t: int) -> int:
    """End of the task/load in progress on resource ``rid`` at time t (no preemption), else t."""
    end = t
    for a in base.assignments:
        if rid in a.resources.values() and a.start_min < t < a.end_min:
            end = max(end, a.end_min)
    return end


def apply_event(snap: ScenarioSnapshot, base: ScheduleResult, ev: DisruptionSpec) -> AppliedEvent:
    t = ev.time_min
    H = snap.horizon_min
    s = snap.model_copy(deep=True)
    out = AppliedEvent(snapshot=s)
    p = ev.payload
    rmap = s.resource_map()

    if ev.event_type in ("worker_absence", "pack_station_outage", "dock_outage"):
        kind = {"worker_absence": "worker", "pack_station_outage": "pack_station", "dock_outage": "dock"}[ev.event_type]
        rid = ev.affected_id or ""
        r = rmap.get(rid)
        if r is None or r.kind != kind:
            raise ValueError(f"{ev.event_type}: unknown {kind} '{rid}'")
        start = _busy_until(base, rid, t)
        if start > t:
            out.exceptions.append(f"{rid}: in-progress work finishes at t={start} before the {ev.event_type} applies")
        end = min(H, t + int(p["duration_min"])) if p.get("duration_min") else H
        r.available = _cut(r.available, start, end)
        out.affected_resources.append(rid)
    elif ev.event_type == "vehicle_breakdown":
        vid = ev.affected_id or ""
        v = s.vehicle_map().get(vid)
        if v is None:
            raise ValueError(f"vehicle_breakdown: unknown vehicle '{vid}'")
        route = next((r for r in base.routes if r.vehicle_id == vid and r.stops), None)
        started = (
            route is not None
            and (route.load_start_min if route.load_start_min is not None else route.departure_min) < t
        )
        if started:
            out.exceptions.append(
                f"{vid}: breakdown after loading/departure — route kept as executed "
                "(mid-route recovery not modelled in MVP)"
            )
        v.available = False
        out.affected_vehicles.append(vid)
    elif ev.event_type == "travel_time_increase":
        factor = float(p.get("factor", 1.3))
        if factor < 1.0:
            raise ValueError("travel_time_increase factor must be ≥ 1")
        dur = [
            [0 if i == j else math.ceil(d * factor) for j, d in enumerate(row)]
            for i, row in enumerate(s.travel.duration_min)
        ]
        s.travel = s.travel.model_copy(
            update={
                "duration_min": dur,
                "version": f"{s.travel.version}+x{factor:g}@{t}",
                "notes": f"{s.travel.notes} · durations ×{factor:g} from t={t} (disruption event; still synthetic)",
            }
        )
        out.timing_changed = True
    elif ev.event_type == "order_cancellation":
        oid = ev.affected_id or ""
        if oid not in s.order_map():
            raise ValueError(f"order_cancellation: unknown order '{oid}'")
        if any(a.start_min < t for a in base.assignments if oid in a.order_ids and a.task_type != "LOAD"):
            out.exceptions.append(f"{oid}: cancelled after work started — executed work kept as history")
        if oid not in s.cancelled_order_ids:
            s.cancelled_order_ids = sorted([*s.cancelled_order_ids, oid])
        out.affected_orders.append(oid)
    elif ev.event_type == "urgent_order":
        oid = str(p.get("order_id") or ev.affected_id or f"URG-{t}")
        if oid in s.order_map():
            raise ValueError(f"urgent_order: order id '{oid}' already exists")
        cust = str(p.get("customer_id", ""))
        if cust not in s.customer_map():
            raise ValueError(f"urgent_order: unknown customer '{cust}'")
        lines = [(str(a), int(b)) for a, b in p.get("lines", [])]
        skus = {k.id: k for k in s.skus}
        if not lines or any(sku not in skus or q <= 0 for sku, q in lines):
            raise ValueError("urgent_order: lines must reference known SKUs with qty > 0")
        due = int(p.get("due_min", t + int(p.get("due_offset_min", 120))))
        order, tasks = make_order(oid, cust, t, due, int(p.get("priority", 3)), lines, skus, s.resources, s.task_model)
        s.orders = [*s.orders, order]
        s.tasks = [*s.tasks, *tasks]
        out.affected_orders.append(oid)
    s.events_applied = [
        *s.events_applied,
        {"event_type": ev.event_type, "time_min": t, "affected_id": ev.affected_id, "payload": p},
    ]
    return out
