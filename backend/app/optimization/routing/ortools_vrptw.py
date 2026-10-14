"""OR-Tools Routing VRPTW.

Nodes = routing units (+ depot 0).  Dimensions:
  * Weight / Volume capacity (per vehicle)
  * Time: transit = service(i) + travel(i,j); slack (waiting) allowed; node windows
    [tw_start, tw_end] hard, or [tw_start, ∞) with SoftUpperBound(tw_end, late_penalty·priority) in soft mode;
    vehicle start ∈ [shift_start, H], end ≤ shift_end (and ≤ H).
  * Goods readiness: start(v) ≥ ready_u + load(n_u)·[u on v]  (conditional constraint per unit/vehicle).
Arc cost = vehicle cost_per_km · km (per-vehicle evaluator); fixed vehicle cost; disjunction penalty
(= unserved penalty × Σ priority) lets the solver drop units explicitly instead of failing.
Search: PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH within the time limit. Routing search never proves
optimality → results are reported as FEASIBLE (no gap).
"""

from __future__ import annotations

import time

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.optimization.common.contracts import CancellationToken
from app.optimization.routing.units import Simulator, Unit


def solve_vrptw(
    sim: Simulator,
    units: list[Unit],
    time_limit_s: float,
    seed: int,
    cancel: CancellationToken | None = None,
    hint: dict[str, list[Unit]] | None = None,
) -> tuple[dict[str, list[Unit]], list[Unit], dict]:
    ctx = sim.ctx
    snap = ctx.snap
    H = snap.horizon_min
    frozen = {fr.vehicle_id for fr in snap.frozen_routes}
    vehicles = [v for v in snap.vehicles if v.available and v.id not in frozen]
    if not vehicles or not units:
        return {v.id: [] for v in vehicles}, list(units), {"routing_status": "TRIVIAL"}
    n = len(units) + 1
    locs = [sim.depot] + [u.loc for u in units]
    manager = pywrapcp.RoutingIndexManager(n, len(vehicles), 0)
    routing = pywrapcp.RoutingModel(manager)
    T, D = sim.T, sim.D

    for vi, v in enumerate(vehicles):

        def arc_cost(i: int, j: int, v=v) -> int:
            a, b = manager.IndexToNode(i), manager.IndexToNode(j)
            return int(round(D[locs[a]][locs[b]] / 1000 * v.cost_per_km))

        cb = routing.RegisterTransitCallback(arc_cost)
        routing.SetArcCostEvaluatorOfVehicle(cb, vi)
        routing.SetFixedCostOfVehicle(int(round(v.fixed_cost)), vi)

    def demand_kg(i: int) -> int:
        node = manager.IndexToNode(i)
        return 0 if node == 0 else units[node - 1].kg

    def demand_l(i: int) -> int:
        node = manager.IndexToNode(i)
        return 0 if node == 0 else units[node - 1].liters

    kg_cb = routing.RegisterUnaryTransitCallback(demand_kg)
    routing.AddDimensionWithVehicleCapacity(kg_cb, 0, [v.capacity_kg for v in vehicles], True, "kg")
    l_cb = routing.RegisterUnaryTransitCallback(demand_l)
    routing.AddDimensionWithVehicleCapacity(l_cb, 0, [v.capacity_l for v in vehicles], True, "liters")

    def transit(i: int, j: int) -> int:
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        svc = 0 if a == 0 else units[a - 1].service
        return svc + T[locs[a]][locs[b]]

    t_cb = routing.RegisterTransitCallback(transit)
    routing.AddDimension(t_cb, H, 4 * H, False, "time")
    time_dim = routing.GetDimensionOrDie("time")
    hard = snap.params.time_window_mode == "hard"
    w = snap.weights
    for k, u in enumerate(units, start=1):
        idx = manager.NodeToIndex(k)
        if hard:
            time_dim.CumulVar(idx).SetRange(u.tw_start, u.tw_end)
        else:
            time_dim.CumulVar(idx).SetMin(u.tw_start)
            time_dim.SetCumulVarSoftUpperBound(idx, u.tw_end, int(round(w.late_penalty_per_min * u.prio)))
        routing.AddDisjunction([idx], int(round(w.unserved_penalty * u.prio)))
    solver = routing.solver()
    for vi, v in enumerate(vehicles):
        s_idx, e_idx = routing.Start(vi), routing.End(vi)
        time_dim.CumulVar(s_idx).SetRange(max(v.shift_start, snap.current_time_min), H)
        time_dim.CumulVar(e_idx).SetMax(min(v.shift_end, H))
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(s_idx))
        for k, u in enumerate(units, start=1):
            need = u.ready + sim.load_fn(len(u.order_ids))
            if need > v.shift_start:
                is_on = routing.VehicleVar(manager.NodeToIndex(k)) == vi
                solver.Add(time_dim.CumulVar(s_idx) >= need * is_on)
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(e_idx))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    params.log_search = False
    _ = seed  # routing search is deterministic for a fixed model; seed recorded for provenance

    if cancel is not None:
        routing.AddAtSolutionCallback(lambda: routing.solver().FinishCurrentSearch() if cancel.cancelled else None)

    t0 = time.perf_counter()
    assignment = None
    if hint:
        uidx = {u.id: k for k, u in enumerate(units, start=1)}
        init = [[uidx[u.id] for u in hint.get(v.id, []) if u.id in uidx] for v in vehicles]
        initial = routing.ReadAssignmentFromRoutes(init, True)
        if initial is not None:
            assignment = routing.SolveFromAssignmentWithParameters(initial, params)
    if assignment is None:
        assignment = routing.SolveWithParameters(params)
    wall = time.perf_counter() - t0
    meta = {
        "routing_solver": "ortools.routing",
        "routing_status": int(routing.status()),
        "first_solution": "PATH_CHEAPEST_ARC" if not hint else "warm_start_from_insertion",
        "metaheuristic": "GUIDED_LOCAL_SEARCH",
        "routing_wall_s": round(wall, 3),
        "stopped_by_time_limit": wall >= time_limit_s * 0.95,
        "optimality": "not proven (local search)",
    }
    if assignment is None:
        meta["routing_has_solution"] = False
        return {v.id: [] for v in vehicles}, list(units), meta
    meta.update(routing_has_solution=True, routing_objective=assignment.ObjectiveValue())
    routes: dict[str, list[Unit]] = {}
    served: set[int] = set()
    for vi, v in enumerate(vehicles):
        seq = []
        idx = routing.Start(vi)
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node:
                seq.append(units[node - 1])
                served.add(node)
            idx = assignment.Value(routing.NextVar(idx))
        routes[v.id] = seq
    dropped = [u for k, u in enumerate(units, start=1) if k not in served]
    return routes, dropped, meta
