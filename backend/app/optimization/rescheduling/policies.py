"""Freeze / neighbourhood logic for the KEEP, PARTIAL and FULL rescheduling policies.

Given the base schedule, the event time ``now`` and the post-event snapshot:
  executed   = work that started before ``now`` (tasks: start < now; routes: loading started < now)
               → always frozen, never rewritten (history);
  affected   = non-executed work made infeasible/invalid by the event (cancelled order, resource no
               longer available during the slot, vehicle unavailable, dock outage over the load,
               travel times changed) plus its dependency closure: all tasks of an affected order and
               the route carrying it (route-mates keep their frozen warehouse work);
  PARTIAL    additionally opens the neighbourhood around the disrupted resources: every non-executed
             task on an affected worker/station/equipment, and every route whose loading has not
             started (vehicles and docks are shared by all routes);
  KEEP       freezes everything that is not affected → only directly impacted work is re-planned;
             impossible re-insertions surface as explicit unserved exceptions;
  PARTIAL    freezes everything outside the neighbourhood and re-optimises inside it;
  FULL       freezes only executed work and the committed window [now, now + freeze_window) that is
             not affected, then re-optimises everything else.
Consistency: a route is frozen only if all tasks of its orders are frozen; tasks of one order are
frozen together.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.optimization.common.contracts import (
    FrozenAssignment,
    FrozenRoute,
    ScenarioSnapshot,
    ScheduleResult,
    VehicleRoute,
)
from app.optimization.rescheduling.events import AppliedEvent, DisruptionSpec, apply_event

Policy = Literal["KEEP", "PARTIAL", "FULL"]


class FreezePlan(BaseModel):
    policy: Policy
    now: int
    freeze_window_min: int
    executed_tasks: int
    frozen_tasks: int
    replanned_tasks: int
    frozen_routes: int
    replanned_routes: int
    affected_orders: list[str]
    exceptions: list[str]


def _route_start(r: VehicleRoute) -> int:
    return r.load_start_min if r.load_start_min is not None else r.departure_min


def _fits(snap: ScenarioSnapshot, rid: str, s: int, e: int) -> bool:
    r = snap.resource_map().get(rid)
    return r is not None and any(w.start <= s and e <= w.end for w in r.available)


def build_policy_snapshot(
    snap: ScenarioSnapshot,
    base: ScheduleResult,
    ev: DisruptionSpec,
    policy: Policy,
    freeze_window_min: int = 30,
) -> tuple[ScenarioSnapshot, FreezePlan]:
    applied: AppliedEvent = apply_event(snap, base, ev)
    s = applied.snapshot
    now = ev.time_min
    cancelled = set(s.cancelled_order_ids)
    vmap = s.vehicle_map()
    wh = [a for a in base.assignments if a.task_type != "LOAD"]
    routes = [r for r in base.routes if r.stops]
    route_of = {o: r.vehicle_id for r in routes for o in r.order_ids}

    executed_t = {a.task_id for a in wh if a.start_min < now}
    executed_r = {r.vehicle_id for r in routes if _route_start(r) < now}

    # ---- direct impact ----
    aff_orders: set[str] = set(applied.affected_orders)
    for a in wh:
        if a.task_id in executed_t:
            continue
        fits = all(_fits(s, rid, a.start_min, a.end_min) for rid in a.resources.values())
        if a.order_ids[0] in cancelled or not fits:
            aff_orders.add(a.order_ids[0])
    aff_routes: set[str] = set()
    for r in routes:
        if r.vehicle_id in executed_r:
            continue
        dock_ok = (
            r.dock_id is None
            or r.load_start_min is None
            or _fits(s, r.dock_id, r.load_start_min, r.load_end_min or r.load_start_min)
        )
        if (
            not vmap[r.vehicle_id].available
            or not dock_ok
            or applied.timing_changed
            or any(o in cancelled for o in r.order_ids)
        ):
            aff_routes.add(r.vehicle_id)
    # PARTIAL neighbourhood: all non-executed warehouse work on disrupted resources, and — because
    # vehicles/docks are shared by every route — all routes whose loading has not started whenever
    # any order or route needs re-planning.
    if policy == "PARTIAL":
        hot = set(applied.affected_resources)
        hot |= {
            rid
            for a in wh
            if a.order_ids[0] in aff_orders and a.task_id not in executed_t
            for rid in a.resources.values()
        }
        for a in wh:
            if a.task_id not in executed_t and hot & set(a.resources.values()) & {
                x.id for x in s.resources if x.kind != "dock"
            }:
                aff_orders.add(a.order_ids[0])
        if aff_orders or aff_routes or applied.affected_vehicles:
            aff_routes |= {r.vehicle_id for r in routes if r.vehicle_id not in executed_r}

    # ---- dependency closure: re-planned tasks change readiness → their route is re-planned.
    # (A re-planned route does NOT force its orders' warehouse tasks to move: they stay frozen.)
    for o in aff_orders:
        v = route_of.get(o)
        if v and v not in executed_r:
            aff_routes.add(v)

    # ---- freeze decision ----
    def task_frozen(a) -> bool:  # type: ignore[no-untyped-def]
        if a.task_id in executed_t:
            return True
        if a.order_ids[0] in aff_orders:
            return False
        if policy == "FULL":
            return a.start_min < now + freeze_window_min
        return True  # KEEP / PARTIAL: outside the affected neighbourhood

    frozen_by_order: dict[str, bool] = {}
    for a in wh:
        o = a.order_ids[0]
        frozen_by_order[o] = frozen_by_order.get(o, True) and task_frozen(a)
    frozen_tasks = [a for a in wh if a.task_id in executed_t or frozen_by_order.get(a.order_ids[0], False)]

    def route_frozen(r: VehicleRoute) -> bool:
        if r.vehicle_id in executed_r:
            return True
        if r.vehicle_id in aff_routes:
            return False
        if policy == "FULL" and _route_start(r) >= now + freeze_window_min:
            return False
        return all(frozen_by_order.get(o, False) for o in r.order_ids)

    fr_routes = [r for r in routes if route_frozen(r)]
    # tasks of orders on frozen routes must be frozen (they feed a fixed loading time)
    frozen_ids = {a.task_id for a in frozen_tasks}
    for r in fr_routes:
        for a in wh:
            if a.order_ids[0] in r.order_ids and a.task_id not in frozen_ids:
                frozen_tasks.append(a)
                frozen_ids.add(a.task_id)

    s.current_time_min = now
    s.frozen_assignments = [
        FrozenAssignment(
            task_id=a.task_id,
            resources=dict(a.resources),
            start_min=a.start_min,
            end_min=a.end_min,
            reason="completed" if a.end_min <= now else ("in_progress" if a.start_min < now else "committed"),
        )
        for a in sorted(frozen_tasks, key=lambda x: (x.start_min, x.task_id))
    ]
    s.frozen_routes = [
        FrozenRoute(
            vehicle_id=r.vehicle_id,
            order_ids=list(r.order_ids),
            dock_id=r.dock_id,
            load_start=r.load_start_min if r.load_start_min is not None else r.departure_min,
            load_end=r.load_end_min if r.load_end_min is not None else r.departure_min,
            departure_min=r.departure_min,
            reason="completed" if r.return_min <= now else ("in_progress" if _route_start(r) < now else "committed"),
            route=r,
        )
        for r in fr_routes
    ]
    s.baseline_assignments = list(base.assignments)
    s.baseline_routes = list(base.routes)
    s.reschedule_policy = policy
    if policy == "KEEP":
        s.keep_frozen_assignments, s.keep_frozen_routes = list(s.frozen_assignments), list(s.frozen_routes)
    else:
        keep_snap, _ = build_policy_snapshot(snap, base, ev, "KEEP", freeze_window_min)
        s.keep_frozen_assignments, s.keep_frozen_routes = keep_snap.frozen_assignments, keep_snap.frozen_routes
    plan = FreezePlan(
        policy=policy,
        now=now,
        freeze_window_min=freeze_window_min,
        executed_tasks=len(executed_t),
        frozen_tasks=len(frozen_tasks),
        replanned_tasks=len(wh) - len(frozen_tasks),
        frozen_routes=len(fr_routes),
        replanned_routes=len(routes) - len(fr_routes),
        affected_orders=sorted(aff_orders),
        exceptions=applied.exceptions,
    )
    return s, plan


def recommend(results: dict[str, dict], weights: dict[str, float] | None = None) -> dict:
    """Pick the best feasible policy by a transparent weighted score (lower is better).

    Each criterion is min-max normalised to [0, 1] across the feasible candidates (0 = best), so no
    criterion dominates just because of its scale (e.g. 3 ms vs 300 ms runtimes):
        score = w_cost·n(total_cost) + w_late·n(lateness) + w_change·n(changed tasks+routes) + w_rt·n(runtime)
    ``total_cost`` already contains unserved and schedule-change penalties. Ties → policy name.
    """
    w = {"cost": 1.0, "lateness": 0.5, "changes": 0.5, "runtime": 0.05, **(weights or {})}
    feas = {k: v for k, v in results.items() if v.get("feasible")}
    if not feas:
        return {"recommended": None, "reason": "no feasible policy result", "scores": {}}
    crit = {
        "cost": {k: float(v["total_cost"]) for k, v in feas.items()},
        "lateness": {k: float(v["late_min"]) for k, v in feas.items()},
        "changes": {k: float(v["changed_tasks"] + v["changed_routes"]) for k, v in feas.items()},
        "runtime": {k: float(v["runtime_ms"]) for k, v in feas.items()},
    }

    def norm(vals: dict[str, float], k: str) -> float:
        lo, hi = min(vals.values()), max(vals.values())
        return 0.0 if hi - lo < 1e-9 else (vals[k] - lo) / (hi - lo)

    scores = {k: round(sum(w[c] * norm(crit[c], k) for c in crit), 4) for k in feas}
    best = min(scores, key=lambda k: (scores[k], k))
    v = feas[best]
    return {
        "recommended": best,
        "scores": scores,
        "weights": w,
        "normalisation": "min-max per criterion",
        "reason": (
            f"{best}: lowest weighted score {scores[best]} — total cost {v['total_cost']:,.0f} "
            f"(incl. unserved/change penalties), lateness {v['late_min']} min, {v['changed_tasks']} changed "
            f"tasks / {v['changed_routes']} changed routes, runtime {v['runtime_ms']} ms "
            "(rule-based selector, not ML)"
        ),
    }
