"""Routing units and a fast route simulator shared by all VRPTW algorithms.

Unit = the orders of one customer delivered at one stop (aggregate mode), split greedily when they
exceed the largest vehicle; in non-aggregate mode every order is its own unit.  The simulator
mirrors ``common.routes.time_route`` exactly (earliest departure, waiting allowed, service once
per stop) so heuristic decisions agree with the shared evaluator/validator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.optimization.common.routes import Ctx, RoutePlan


@dataclass(frozen=True)
class Unit:
    id: str
    order_ids: tuple[str, ...]
    customer_id: str
    loc: int
    kg: int
    liters: int
    ready: int
    tw_start: int
    tw_end: int
    service: int
    prio: int  # Σ order priority (penalty multiplier)


LoadFn = Callable[[int], int]  # minutes of loading before departure for n orders (0 for routing-only)


def build_units(ctx: Ctx, order_ids: list[str], ready: dict[str, int]) -> list[Unit]:
    vehicles = [v for v in ctx.snap.vehicles if v.available]
    cap_kg = max((v.capacity_kg for v in vehicles), default=0)
    cap_l = max((v.capacity_l for v in vehicles), default=0)
    by_c: dict[str, list[str]] = {}
    for oid in sorted(order_ids):
        key = ctx.om[oid].customer_id if ctx.snap.params.aggregate_same_customer else oid
        by_c.setdefault(key, []).append(oid)
    units: list[Unit] = []
    for _key, oids in sorted(by_c.items()):
        chunk: list[str] = []
        for oid in sorted(oids, key=lambda o: (-ctx.om[o].weight_kg, o)):
            kg, lt = ctx.weight(chunk + [oid])
            if chunk and (kg > cap_kg or lt > cap_l):
                units.append(_mk(ctx, chunk, ready, len(units)))
                chunk = []
            chunk.append(oid)
        if chunk:
            units.append(_mk(ctx, chunk, ready, len(units)))
    return units


def _mk(ctx: Ctx, oids: list[str], ready: dict[str, int], i: int) -> Unit:
    c = ctx.cm[ctx.om[oids[0]].customer_id]
    kg, lt = ctx.weight(oids)
    return Unit(
        id=f"U{i:04d}-{c.id}",
        order_ids=tuple(sorted(oids)),
        customer_id=c.id,
        loc=ctx.li[c.location_id],
        kg=kg,
        liters=lt,
        ready=max(ready.get(o, 0) for o in oids),
        tw_start=c.tw_start,
        tw_end=c.tw_end,
        service=c.service_min,
        prio=sum(ctx.om[o].priority for o in oids),
    )


@dataclass
class Sim:
    ok: bool  # hard constraints satisfied (capacity, shift/horizon, hard windows)
    cost: float  # fixed (if used) + distance + late penalty
    late_min: int
    dist_m: int
    departure: int
    ret: int


class Simulator:
    def __init__(self, ctx: Ctx, load_fn: LoadFn | None = None):
        self.ctx = ctx
        self.load_fn = load_fn or (lambda n: 0)
        s = ctx.snap
        self.T = s.travel.duration_min
        self.D = s.travel.distance_m
        self.depot = ctx.depot
        self.hard = s.params.time_window_mode == "hard"
        self.ret_depot = s.params.return_to_depot
        self.late_w = s.weights.late_penalty_per_min
        self.H = s.horizon_min
        self.now = s.current_time_min

    def departure(self, vid: str, seq: list[Unit]) -> int:
        v = self.ctx.vm[vid]
        n = sum(len(u.order_ids) for u in seq)
        return max([v.shift_start, self.now] + [u.ready for u in seq]) + self.load_fn(n)

    def run(self, vid: str, seq: list[Unit]) -> Sim:
        v = self.ctx.vm[vid]
        if not seq:
            return Sim(True, 0.0, 0, 0, 0, 0)
        kg = sum(u.kg for u in seq)
        lt = sum(u.liters for u in seq)
        ok = kg <= v.capacity_kg and lt <= v.capacity_l
        dep = self.departure(vid, seq)
        t, prev, dist, late, pen = dep, self.depot, 0, 0, 0.0
        T, D = self.T, self.D
        for u in seq:
            arr = t + T[prev][u.loc]
            dist += D[prev][u.loc]
            st = arr if arr > u.tw_start else u.tw_start
            if st > u.tw_end:
                lm = st - u.tw_end
                late += lm
                pen += lm * self.late_w * u.prio
                if self.hard:
                    ok = False
            t = st + u.service
            prev = u.loc
        if self.ret_depot:
            dist += D[prev][self.depot]
            t += T[prev][self.depot]
        if t > v.shift_end or t > self.H:
            ok = False
        cost = v.fixed_cost + dist / 1000 * v.cost_per_km + pen
        return Sim(ok, cost, late, dist, dep, t)


def plans_from_routes(routes: dict[str, list[Unit]]) -> list[RoutePlan]:
    out = []
    for vid in sorted(routes):
        seq = routes[vid]
        if seq:
            out.append(RoutePlan(vid, [list(u.order_ids) for u in seq], max(u.ready for u in seq)))
    return out
