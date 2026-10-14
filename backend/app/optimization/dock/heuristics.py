"""Dock/vehicle loading appointment heuristics (FIFO by readiness, EDD by delivery slack).

Each route plan (vehicle + ordered stops) needs one LOAD interval on a compatible dock:
    load_start ≥ max(ready (all orders packed), vehicle shift start, now)
    load_end   = load_start + load_base + load_per_order·n
    departure  = load_end
Placement = earliest feasible start over compatible docks (dock hours/downtime, no overlap),
then hard-constraint repair (drop stops that break shift end / hard windows).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.optimization.common.contracts import VehicleRoute
from app.optimization.common.routes import Ctx, RoutePlan, compatible_docks, repair_plan, slack_departure
from app.optimization.common.timeline import Timeline


@dataclass
class DockOutcome:
    routes: list[VehicleRoute] = field(default_factory=list)
    unserved: dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def dock_timelines(ctx: Ctx) -> dict[str, Timeline]:
    tls = {r.id: Timeline(r.available) for r in ctx.snap.resources if r.kind == "dock"}
    for fr in ctx.snap.frozen_routes:
        if fr.dock_id in tls:
            tls[fr.dock_id].reserve(fr.load_start, fr.load_end)
    return tls


def earliest_load(ctx: Ctx, plan: RoutePlan) -> int:
    v = ctx.vm[plan.vehicle_id]
    return max(plan.ready_min, v.shift_start, ctx.snap.current_time_min)


def assign_docks_dispatch(ctx: Ctx, plans: list[RoutePlan], rule: str) -> DockOutcome:
    tls = dock_timelines(ctx)
    out = DockOutcome(metadata={"rule": rule, "scheme": "earliest-feasible dock insertion + hard repair"})
    if rule == "fifo":
        order = sorted(plans, key=lambda p: (p.ready_min, p.vehicle_id))
    else:  # edd: least delivery slack first
        order = sorted(plans, key=lambda p: (slack_departure(ctx, p), p.ready_min, p.vehicle_id))
    for plan in order:
        if not plan.stops:
            continue
        docks = compatible_docks(ctx, plan.vehicle_id)
        est = earliest_load(ctx, plan)
        dur = ctx.load_minutes(len(plan.order_ids))
        best: tuple[int, str] | None = None
        for d in docks:
            s = tls[d].earliest_fit(est, dur)
            if s is not None and (best is None or (s, d) < best):
                best = (s, d)
        if best is None:
            for oid in plan.order_ids:
                out.unserved[oid] = "no_feasible_dock_slot"
            continue
        start, dock = best
        plan.dock_id, plan.load_start = dock, start
        plan, route, dropped = repair_plan(ctx, plan, lambda p: p.load_start + ctx.load_minutes(len(p.order_ids)))
        out.unserved.update(dropped)
        if route is None:
            continue
        tls[dock].reserve(route.load_start_min, route.load_end_min)  # type: ignore[arg-type]
        out.routes.append(route)
    return out
