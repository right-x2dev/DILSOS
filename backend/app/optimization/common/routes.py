"""Route timing / feasibility helpers shared by dock, routing and integrated algorithms.

A route plan is an ordered list of *stops*; a stop is a list of order ids for one customer
(orders of the same customer are aggregated into one stop when ``params.aggregate_same_customer``).
Time propagation (deterministic, integer minutes):
    arrival_k   = departure_{k-1} + travel(prev, k)
    start_k     = max(arrival_k, tw_start_k)          (waiting allowed; tw_start always hard)
    end_k       = start_k + service_min_k
    departure_k = end_k
    return      = departure_last + travel(last, depot)   (if return_to_depot)
Late minutes = max(0, start_k − tw_end_k): error in hard mode, penalised in soft mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.optimization.common.contracts import RouteStop, ScenarioSnapshot, TaskAssignment, VehicleRoute


@dataclass
class RoutePlan:
    vehicle_id: str
    stops: list[list[str]]  # order ids per stop, in visit order
    ready_min: int = 0
    dock_id: str | None = None
    load_start: int | None = None

    @property
    def order_ids(self) -> list[str]:
        return [o for s in self.stops for o in s]


@dataclass
class Ctx:
    """Pre-computed lookups (build once per solve)."""

    snap: ScenarioSnapshot
    om: dict = field(init=False)
    cm: dict = field(init=False)
    vm: dict = field(init=False)
    li: dict = field(init=False)

    def __post_init__(self) -> None:
        s = self.snap
        self.om, self.cm, self.vm, self.li = s.order_map(), s.customer_map(), s.vehicle_map(), s.loc_index()

    def loc_of_order(self, oid: str) -> int:
        return self.li[self.cm[self.om[oid].customer_id].location_id]

    @property
    def depot(self) -> int:
        return self.li[self.snap.depot_location_id]

    def travel(self, a: int, b: int) -> int:
        return self.snap.travel.duration_min[a][b]

    def dist(self, a: int, b: int) -> int:
        return self.snap.travel.distance_m[a][b]

    def load_minutes(self, n_orders: int) -> int:
        p = self.snap.params
        return p.load_base_min + p.load_per_order_min * n_orders

    def weight(self, oids: list[str]) -> tuple[int, int]:
        return sum(self.om[o].weight_kg for o in oids), sum(self.om[o].volume_l for o in oids)


def group_stops(ctx: Ctx, seq: list[str]) -> list[list[str]]:
    """Order sequence → stops (merge *consecutive* same-customer orders when aggregation is on)."""
    stops: list[list[str]] = []
    agg = ctx.snap.params.aggregate_same_customer
    for oid in seq:
        if agg and stops and ctx.om[stops[-1][0]].customer_id == ctx.om[oid].customer_id:
            stops[-1].append(oid)
        else:
            stops.append([oid])
    return stops


def time_route(ctx: Ctx, plan: RoutePlan, departure: int) -> VehicleRoute:
    snap = ctx.snap
    kg, lt = ctx.weight(plan.order_ids)
    rem_kg, rem_l = kg, lt
    prev = ctx.depot
    t = departure
    dist = 0
    stops: list[RouteStop] = []
    for i, oids in enumerate(plan.stops):
        c = ctx.cm[ctx.om[oids[0]].customer_id]
        loc = ctx.li[c.location_id]
        arr = t + ctx.travel(prev, loc)
        dist += ctx.dist(prev, loc)
        start = max(arr, c.tw_start)
        end = start + c.service_min
        okg, ol = ctx.weight(oids)
        rem_kg -= okg
        rem_l -= ol
        stops.append(
            RouteStop(
                seq=i + 1,
                customer_id=c.id,
                location_id=c.location_id,
                order_ids=list(oids),
                arrival_min=arr,
                service_start_min=start,
                service_end_min=end,
                departure_min=end,
                wait_min=start - arr,
                late_min=max(0, start - c.tw_end),
                load_after_kg=rem_kg,
                load_after_l=rem_l,
            )
        )
        t, prev = end, loc
    ret = t
    if snap.params.return_to_depot and stops:
        ret = t + ctx.travel(prev, ctx.depot)
        dist += ctx.dist(prev, ctx.depot)
    load_end = None
    if plan.load_start is not None:
        load_end = plan.load_start + ctx.load_minutes(len(plan.order_ids))
    return VehicleRoute(
        vehicle_id=plan.vehicle_id,
        dock_id=plan.dock_id,
        order_ids=plan.order_ids,
        ready_min=plan.ready_min,
        load_start_min=plan.load_start,
        load_end_min=load_end,
        departure_min=departure,
        return_min=ret,
        stops=stops,
        distance_m=dist,
        load_kg=kg,
        load_l=lt,
    )


def hard_violations(ctx: Ctx, route: VehicleRoute) -> list[tuple[str, int]]:
    """List of (kind, stop index or -1) hard violations: capacity, shift end, horizon, hard windows."""
    v = ctx.vm[route.vehicle_id]
    out: list[tuple[str, int]] = []
    if route.load_kg > v.capacity_kg or route.load_l > v.capacity_l:
        out.append(("capacity", -1))
    if route.return_min > v.shift_end or route.return_min > ctx.snap.horizon_min:
        out.append(("shift_end", len(route.stops) - 1))
    if ctx.snap.params.time_window_mode == "hard":
        out += [("time_window", i) for i, s in enumerate(route.stops) if s.late_min > 0]
    return out


def slack_departure(ctx: Ctx, plan: RoutePlan) -> int:
    """Latest departure with no lateness, ignoring waiting (EDD key for docks)."""
    t, prev, best = 0, ctx.depot, 10**9
    for oids in plan.stops:
        c = ctx.cm[ctx.om[oids[0]].customer_id]
        loc = ctx.li[c.location_id]
        t += ctx.travel(prev, loc)
        best = min(best, c.tw_end - t)
        t += c.service_min
        prev = loc
    return best


def repair_plan(ctx: Ctx, plan: RoutePlan, departure_fn) -> tuple[RoutePlan, VehicleRoute | None, dict[str, str]]:  # type: ignore[no-untyped-def]
    """Drop stops until the timed route satisfies all hard constraints.

    ``departure_fn(plan) -> int`` recomputes the departure after each removal (load gets shorter).
    Returns (plan, route or None if emptied, {order_id: reason}).
    """
    dropped: dict[str, str] = {}
    while plan.stops:
        dep = departure_fn(plan)
        route = time_route(ctx, plan, dep)
        viol = hard_violations(ctx, route)
        if not viol:
            return plan, route, dropped
        kind, idx = viol[0]
        if kind == "capacity":  # drop the heaviest stop
            idx = max(range(len(plan.stops)), key=lambda i: (ctx.weight(plan.stops[i])[0], -i))
        reason = {
            "capacity": "exceeds_vehicle_capacity",
            "shift_end": "route_exceeds_vehicle_shift",
            "time_window": "time_window_infeasible",
        }[kind]
        for oid in plan.stops[idx]:
            dropped[oid] = reason
        plan = RoutePlan(
            plan.vehicle_id, plan.stops[:idx] + plan.stops[idx + 1 :], plan.ready_min, plan.dock_id, plan.load_start
        )
    return plan, None, dropped


def load_assignment(route: VehicleRoute) -> TaskAssignment:
    assert route.dock_id is not None and route.load_start_min is not None and route.load_end_min is not None
    return TaskAssignment(
        task_id=f"LOAD-{route.vehicle_id}",
        task_type="LOAD",
        order_ids=list(route.order_ids),
        resource_id=route.dock_id,
        resources={"dock": route.dock_id},
        start_min=route.load_start_min,
        end_min=route.load_end_min,
    )


def compatible_docks(ctx: Ctx, vehicle_id: str) -> list[str]:
    vc = ctx.vm[vehicle_id].vehicle_class
    return [r.id for r in ctx.snap.resources if r.kind == "dock" and (not r.vehicle_classes or vc in r.vehicle_classes)]
