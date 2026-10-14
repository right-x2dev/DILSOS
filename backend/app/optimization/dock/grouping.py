"""Fixed baseline order→vehicle grouping used by the *dock-only* problem type (P2).

Deterministic first-fit: orders sorted by (customer tw_end, ready, id) go to the first vehicle
(largest capacity first) with remaining weight/volume capacity and at least one compatible dock;
same-customer orders are kept on one vehicle when possible. Stops are then sequenced by
nearest neighbour from the depot. This is intentionally simple — the routing algorithms of
Phase 3 replace it in the routing/integrated problem types.
"""

from __future__ import annotations

from app.optimization.common.routes import Ctx, RoutePlan, compatible_docks, group_stops, time_route


def nn_sequence(ctx: Ctx, oids: list[str]) -> list[str]:
    """Nearest-neighbour visiting order (ties: earlier tw_end, then id); same-customer orders adjacent."""
    left = sorted(oids)
    seq: list[str] = []
    cur = ctx.depot
    while left:
        nxt = min(left, key=lambda o: (ctx.travel(cur, ctx.loc_of_order(o)), ctx.cm[ctx.om[o].customer_id].tw_end, o))
        seq.append(nxt)
        left.remove(nxt)
        cur = ctx.loc_of_order(nxt)
    return seq


def _trial(ctx: Ctx, vid: str, oids: list[str], ready: dict[str, int]) -> tuple[bool, int]:
    """(on-time & within shift?, total late minutes) for an NN-sequenced trial route."""
    v = ctx.vm[vid]
    seq = nn_sequence(ctx, oids)
    rdy = max([ready.get(o, 0) for o in oids] + [v.shift_start, ctx.snap.current_time_min])
    plan = RoutePlan(vid, group_stops(ctx, seq), rdy)
    r = time_route(ctx, plan, rdy + ctx.load_minutes(len(oids)))
    late = sum(s.late_min for s in r.stops)
    ok = late == 0 and r.return_min <= min(v.shift_end, ctx.snap.horizon_min)
    return ok, late if r.return_min <= min(v.shift_end, ctx.snap.horizon_min) else 10**9


def baseline_grouping(ctx: Ctx, order_ids: list[str], ready: dict[str, int]) -> tuple[list[RoutePlan], dict[str, str]]:
    """Time-aware first-fit: an order joins the first (cheapest) vehicle that stays on-time and
    within shift (estimated with earliest loading); otherwise the vehicle with the least added lateness."""
    frozen_v = {fr.vehicle_id for fr in ctx.snap.frozen_routes}
    vehicles = sorted(
        (v for v in ctx.snap.vehicles if v.available and compatible_docks(ctx, v.id) and v.id not in frozen_v),
        key=lambda v: (v.fixed_cost, -v.capacity_kg, v.id),
    )
    loads = {v.id: [0, 0] for v in vehicles}
    members: dict[str, list[str]] = {v.id: [] for v in vehicles}
    late_now = {v.id: 0 for v in vehicles}
    unserved: dict[str, str] = {}
    key = sorted(order_ids, key=lambda o: (ctx.cm[ctx.om[o].customer_id].tw_end, ready.get(o, 0), o))
    for oid in key:
        o = ctx.om[oid]
        cands = [
            v
            for v in vehicles
            if loads[v.id][0] + o.weight_kg <= v.capacity_kg and loads[v.id][1] + o.volume_l <= v.capacity_l
        ]
        if not cands:
            unserved[oid] = "no_vehicle_capacity"
            continue
        chosen, fallback = None, None
        for v in cands:
            ok, late = _trial(ctx, v.id, members[v.id] + [oid], ready)
            if ok:
                chosen = v
                break
            delta = late - late_now[v.id]
            if fallback is None or delta < fallback[0]:
                fallback = (delta, v, late)
        if chosen is None:
            if fallback is None or fallback[0] >= 10**8:
                unserved[oid] = "route_exceeds_vehicle_shift"
                continue
            chosen = fallback[1]
            late_now[chosen.id] = fallback[2]
        loads[chosen.id][0] += o.weight_kg
        loads[chosen.id][1] += o.volume_l
        members[chosen.id].append(oid)
    plans = []
    for v in vehicles:
        if members[v.id]:
            seq = nn_sequence(ctx, members[v.id])
            plans.append(RoutePlan(v.id, group_stops(ctx, seq), max(ready.get(o, 0) for o in seq)))
    return plans, unserved
