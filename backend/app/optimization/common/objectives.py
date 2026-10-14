"""Shared evaluator: identical cost/KPI logic for every algorithm (never solver-specific objectives).

total_cost = transport_fixed + distance_cost + labor_cost + overtime_cost
           + late_delivery_penalty + unserved_penalty + schedule_change_penalty

Lateness of a served order:
  * routed  → max(0, delivery service start − customer tw_end)
  * otherwise (warehouse scope) → max(0, packing completion − order ship cutoff)
"""

from __future__ import annotations

from app.optimization.common.contracts import (
    CostBreakdown,
    ScenarioSnapshot,
    ScheduleMetrics,
    ScheduleResult,
    TaskAssignment,
    VehicleRoute,
)


def _r2(x: float) -> float:
    return round(x + 0.0, 2)


def stability(
    snap: ScenarioSnapshot, assignments: list[TaskAssignment], routes: list[VehicleRoute]
) -> tuple[int | None, int | None, float | None]:
    """Changed tasks/routes vs. the baseline plan carried in the snapshot (None if no baseline)."""
    if not snap.baseline_assignments and not snap.baseline_routes:
        return None, None, None
    old = {a.task_id: a for a in snap.baseline_assignments}
    new = {a.task_id: a for a in assignments}
    changed = 0
    for tid in set(old) | set(new):
        a, b = old.get(tid), new.get(tid)
        if a is None or b is None or a.start_min != b.start_min or a.resources != b.resources:
            changed += 1
    old_r = {r.vehicle_id: [s.customer_id for s in r.stops] for r in snap.baseline_routes}
    new_r = {r.vehicle_id: [s.customer_id for s in r.stops] for r in routes}
    old_d = {r.vehicle_id: r.departure_min for r in snap.baseline_routes}
    new_d = {r.vehicle_id: r.departure_min for r in routes}
    changed_routes = sum(
        1 for v in set(old_r) | set(new_r) if old_r.get(v) != new_r.get(v) or old_d.get(v) != new_d.get(v)
    )
    denom = max(1, len(set(old) | set(new)) + len(set(old_r) | set(new_r)))
    score = 1.0 - (changed + changed_routes) / denom
    return changed, changed_routes, round(max(0.0, score), 4)


def evaluate(snap: ScenarioSnapshot, result: ScheduleResult) -> ScheduleMetrics:
    w = snap.weights
    om = snap.order_map()
    rmap = snap.resource_map()
    cmap = snap.customer_map()
    vmap = snap.vehicle_map()
    unserved_ids = set(result.unserved_order_ids)
    cancelled = set(snap.cancelled_order_ids)

    labor = overtime_cost = 0.0
    ot_min = 0
    busy: dict[str, int] = {}
    pack_end: dict[str, int] = {}
    wh_end = 0
    for a in result.assignments:
        dur = a.end_min - a.start_min
        for rid in a.resources.values():
            busy[rid] = busy.get(rid, 0) + dur
            res = rmap.get(rid)
            if res is not None and res.kind == "worker":
                labor += dur * res.hourly_cost / 60
                if res.regular_end is not None:
                    ot = max(0, a.end_min - max(a.start_min, res.regular_end))
                    ot_min += ot
                    overtime_cost += ot * res.hourly_cost * w.overtime_premium / 60
        if a.task_type in ("PICK", "PACK"):
            wh_end = max(wh_end, a.end_min)
            for oid in a.order_ids:
                pack_end[oid] = max(pack_end.get(oid, 0), a.end_min)

    transport_fixed = distance_cost = 0.0
    dist_m = 0
    delivered_start: dict[str, int] = {}
    e2e = None
    for r in result.routes:
        if not r.stops:
            continue
        v = vmap[r.vehicle_id]
        transport_fixed += v.fixed_cost
        distance_cost += r.distance_m / 1000 * v.cost_per_km
        dist_m += r.distance_m
        e2e = max(e2e or 0, r.return_min)
        for s in r.stops:
            for oid in s.order_ids:
                delivered_start[oid] = s.service_start_min

    served = [o for o in snap.orders if o.id not in unserved_ids and o.id not in cancelled]
    late_total = late_max = on_time = 0
    late_pen = 0.0
    routed_scope = result.problem_type != "warehouse"
    for o in served:
        if routed_scope:
            if o.id not in delivered_start:
                continue
            late = max(0, delivered_start[o.id] - cmap[o.customer_id].tw_end)
        else:
            if o.id not in pack_end:
                continue
            late = max(0, pack_end[o.id] - o.due_min)
        late_total += late
        late_max = max(late_max, late)
        on_time += late == 0
        late_pen += late * w.late_penalty_per_min * o.priority

    unserved_pen = sum(
        w.unserved_penalty * om[oid].priority for oid in unserved_ids if oid in om and oid not in cancelled
    )
    ch_t, ch_r, stab = stability(snap, result.assignments, result.routes)
    change_pen = (ch_t or 0) * w.change_penalty_per_task + (ch_r or 0) * w.change_penalty_per_route

    util: dict[str, float] = {}
    by_kind: dict[str, list[float]] = {}
    for res in snap.resources:
        avail = sum(max(0, min(i.end, snap.horizon_min) - max(i.start, 0)) for i in res.available)
        if avail <= 0:
            continue
        u = round(busy.get(res.id, 0) / avail, 4)
        util[res.id] = u
        by_kind.setdefault(res.kind, []).append(u)

    total = transport_fixed + distance_cost + labor + overtime_cost + late_pen + unserved_pen + change_pen
    cost = CostBreakdown(
        currency=w.currency,
        transport_fixed=_r2(transport_fixed),
        distance_cost=_r2(distance_cost),
        labor_cost=_r2(labor),
        overtime_cost=_r2(overtime_cost),
        late_delivery_penalty=_r2(late_pen),
        unserved_penalty=_r2(unserved_pen),
        schedule_change_penalty=_r2(change_pen),
        total_cost=_r2(total),
        coefficients={
            "late_penalty_per_min": w.late_penalty_per_min,
            "late_penalty_multiplier": "order.priority",
            "unserved_penalty": w.unserved_penalty,
            "overtime_premium": w.overtime_premium,
            "change_penalty_per_task": w.change_penalty_per_task,
            "change_penalty_per_route": w.change_penalty_per_route,
            "labor": "Σ task minutes × worker hourly_cost / 60",
            "distance": "Σ route km × vehicle cost_per_km",
            "lateness_basis": "delivery vs customer tw_end" if routed_scope else "packing end vs order cutoff",
        },
    )
    return ScheduleMetrics(
        cost=cost,
        orders_total=len(snap.orders),
        orders_served=len(served),
        orders_unserved=len([o for o in unserved_ids if o not in cancelled]),
        on_time_rate=round(on_time / len(served), 4) if served else None,
        total_lateness_min=late_total,
        max_lateness_min=late_max,
        warehouse_makespan_min=wh_end if result.assignments else None,
        end_to_end_makespan_min=e2e,
        total_distance_km=round(dist_m / 1000, 3),
        vehicles_used=sum(1 for r in result.routes if r.stops),
        resource_utilization=util,
        avg_utilization={k: round(sum(v) / len(v), 4) for k, v in by_kind.items()},
        overtime_min=ot_min,
        changed_tasks=ch_t,
        changed_routes=ch_r,
        stability_score=stab,
    )
