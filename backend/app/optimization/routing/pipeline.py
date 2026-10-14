"""Problem type ``routing`` (VRPTW only).

Assumption (documented in the UI): without a warehouse plan, an order's goods are available at its
release time (warehouse treated as instantaneous) — vehicles cannot depart before every assigned
order is released. No dock loading is modelled in this scope; ``integrated`` couples the real
pick/pack readiness and dock appointments.
"""

from __future__ import annotations

import time

from app.optimization.common.contracts import CancellationToken, ScenarioSnapshot, ScheduleResult, SolveConfig
from app.optimization.common.preprocess import prepare, unserved_list
from app.optimization.common.routes import Ctx, RoutePlan, repair_plan
from app.optimization.routing.baseline import cheapest_insertion, nearest_neighbour
from app.optimization.routing.units import Simulator, Unit, build_units, plans_from_routes


def finalize_routing(ctx: Ctx, plans: list[RoutePlan], sim: Simulator) -> tuple[list, dict[str, str]]:
    """Time each plan with the earliest departure, then hard-repair (should be a no-op for valid solvers)."""
    routes, dropped = [], {}
    for p in plans:
        p2, route, d = repair_plan(
            ctx, p, lambda q: max(ctx.vm[q.vehicle_id].shift_start, ctx.snap.current_time_min, q.ready_min)
        )
        dropped.update(d)
        if route is not None:
            routes.append(route)
    return routes, dropped


def plans_with_ready(routes: dict[str, list[Unit]]) -> list[RoutePlan]:
    return plans_from_routes(routes)


class RoutingScheduler:
    supported_problem_types = {"routing"}

    def __init__(self, method: str):
        self.method = method
        self.name = f"routing_{method}"
        self.kind = {"nn": "heuristic", "insertion": "heuristic", "ortools": "metaheuristic"}[method]
        self.description = {
            "nn": "시간지향 최근접 이웃 (Solomon식) + 잔여 최저비용 삽입",
            "insertion": "최저비용 삽입 (고정비+거리+지연, 용량·근무·시간창 유지)",
            "ortools": "OR-Tools Routing VRPTW (용량·시간 차원, GLS)",
        }[method]

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        t0 = time.perf_counter()
        snap = instance
        ctx = Ctx(snap)
        prep = prepare(snap, routing=True)
        reasons = dict(prep.unserved)
        ready = {o.id: o.release_min for o in snap.orders}  # routing-only: warehouse treated as instantaneous
        units = build_units(ctx, prep.servable, ready)
        sim = Simulator(ctx)
        meta: dict = {
            "units": len(units),
            "readiness_assumption": "routing-only: goods ready at order release (warehouse & dock not modelled)",
        }
        if self.method == "nn":
            routes, left = nearest_neighbour(sim, units)
        elif self.method == "insertion":
            routes, left = cheapest_insertion(sim, units)
        else:
            from app.optimization.routing.ortools_vrptw import solve_vrptw

            warm, _ = cheapest_insertion(sim, units) if config.params.get("warm_start", True) else ({}, [])
            routes, left, m = solve_vrptw(sim, units, config.time_limit_s, config.seed, cancel, hint=warm)
            meta.update(m)
        for u in left:
            for oid in u.order_ids:
                reasons[oid] = "no_feasible_route"
        plans = plans_with_ready(routes)
        final, dropped = finalize_routing(ctx, plans, sim)
        reasons.update(dropped)
        return ScheduleResult(
            run_id="",
            algorithm=self.name,
            problem_type="routing",
            status="FEASIBLE",
            assignments=[],
            routes=final,
            unserved_order_ids=sorted(reasons),
            unserved=unserved_list(snap, reasons),
            runtime_ms=int((time.perf_counter() - t0) * 1000),
            seed=config.seed,
            solver_metadata=meta,
        )
