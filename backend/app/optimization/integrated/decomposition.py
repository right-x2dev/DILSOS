"""Integrated pick→pack→load→depart→deliver pipeline built from the shared sub-solvers.

One pass (``compose``):
  1. warehouse plan (EDD/FIFO/SPT SGS or CP-SAT) on a *working copy* of the snapshot whose order
     cutoffs may be tightened by the coordinator;
  2. readiness r_o = packing completion;
  3. VRPTW (insertion / NN / OR-Tools / ALNS) with departure ≥ max r_o + estimated loading time;
  4. dock appointments (EDD dispatch or CP-SAT with exact downstream timing) — the real loading time
     and dock contention may push departures later;
  5. hard repair; orders dropped anywhere become explicitly unserved and their pick/pack work is
     removed so nothing consumes capacity silently.
Every candidate is evaluated with the shared evaluator on the ORIGINAL snapshot and validated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.optimization.common.contracts import (
    CancellationToken,
    ScenarioSnapshot,
    ScheduleResult,
    SolveConfig,
    TaskAssignment,
)
from app.optimization.common.objectives import evaluate
from app.optimization.common.preprocess import prepare, unserved_list
from app.optimization.common.routes import Ctx, load_assignment
from app.optimization.common.validator import validate_schedule
from app.optimization.dock.cp_sat import assign_docks_cpsat
from app.optimization.dock.heuristics import assign_docks_dispatch
from app.optimization.routing.baseline import cheapest_insertion, nearest_neighbour
from app.optimization.routing.units import Simulator, Unit, build_units, plans_from_routes
from app.optimization.warehouse.cp_sat import WarehouseCpSat
from app.optimization.warehouse.heuristics import RULES
from app.optimization.warehouse.sgs import decode


@dataclass
class Settings:
    warehouse: str = "edd"  # fifo | edd | spt | cpsat
    routing: str = "insertion"  # nn | insertion | ortools | alns
    dock: str = "edd"  # edd | fifo | cpsat
    wh_time_s: float = 5.0
    routing_time_s: float = 5.0
    dock_time_s: float = 3.0
    seed: int = 0


@dataclass
class Composite:
    result: ScheduleResult
    wh_assignments: list[TaskAssignment]
    pack_end: dict[str, int]
    routes_units: dict[str, list[Unit]]
    meta: dict = field(default_factory=dict)


def warehouse_plan(work: ScenarioSnapshot, st: Settings, cancel: CancellationToken | None):
    """Return (assignments, pack_end, unserved reasons, metadata) for the working snapshot."""
    prep = prepare(work, routing=True)
    if st.warehouse == "cpsat":
        r = WarehouseCpSat().solve(
            work, SolveConfig(problem_type="warehouse", time_limit_s=st.wh_time_s, seed=st.seed), cancel
        )
        reasons = {u.order_id: u.reason for u in r.unserved}
        # routing-level preprocessing reasons (e.g. exceeds vehicle capacity) take precedence
        reasons.update(prep.unserved)
        pack_end: dict[str, int] = {}
        for a in r.assignments:
            pack_end[a.order_ids[0]] = max(pack_end.get(a.order_ids[0], 0), a.end_min)
        meta = {k: r.solver_metadata.get(k) for k in ("cp_status", "gap", "solver_objective", "best_bound")}
        return [a for a in r.assignments if a.frozen or a.order_ids[0] not in reasons], pack_end, reasons, meta
    res = decode(work, prep, RULES[st.warehouse](work))
    reasons = {**prep.unserved, **res.unserved}
    return res.assignments, res.pack_end, reasons, {"rule": st.warehouse}


def route_orders(
    ctx: Ctx,
    sim: Simulator,
    units: list[Unit],
    st: Settings,
    cancel: CancellationToken | None,
    warm: dict[str, list[Unit]] | None = None,
) -> tuple[dict[str, list[Unit]], list[Unit], dict]:
    if st.routing == "nn":
        r, left = nearest_neighbour(sim, units)
        return r, left, {}
    if st.routing == "insertion":
        r, left = cheapest_insertion(sim, units)
        return r, left, {}
    if st.routing == "alns":
        from app.optimization.routing.alns import alns_search

        start, left = cheapest_insertion(sim, units) if not warm else (_rebase(warm, units), [])
        if warm:
            start, left = cheapest_insertion(sim, [u for u in units if not _contains(start, u)], start)
        r, left2, meta = alns_search(sim, start, left, st.routing_time_s, st.seed, cancel)
        return r, left2, meta
    from app.optimization.routing.ortools_vrptw import solve_vrptw

    hint = _rebase(warm, units) if warm else cheapest_insertion(sim, units)[0]
    return solve_vrptw(sim, units, st.routing_time_s, st.seed, cancel, hint=hint)


def _contains(routes: dict[str, list[Unit]], u: Unit) -> bool:
    return any(x.id == u.id for seq in routes.values() for x in seq)


def _rebase(warm: dict[str, list[Unit]], units: list[Unit]) -> dict[str, list[Unit]]:
    """Map a previous solution onto freshly built units (readiness changed) by order-id signature."""
    by_sig = {u.order_ids: u for u in units}
    return {v: [by_sig[x.order_ids] for x in seq if x.order_ids in by_sig] for v, seq in warm.items()}


def compose(
    snap: ScenarioSnapshot,
    work: ScenarioSnapshot,
    st: Settings,
    name: str,
    cancel: CancellationToken | None = None,
    warm_routes: dict[str, list[Unit]] | None = None,
) -> Composite:
    t0 = time.perf_counter()
    ctx = Ctx(snap)
    wh, pack_end, reasons, wh_meta = warehouse_plan(work, st, cancel)
    fr_orders = {o for fr in snap.frozen_routes for o in fr.order_ids}  # already on an executed/committed route
    packed = sorted(o for o in pack_end if o not in reasons and o not in fr_orders)
    units = build_units(ctx, packed, pack_end)
    sim = Simulator(ctx, load_fn=ctx.load_minutes)
    routes_u, left, r_meta = route_orders(ctx, sim, units, st, cancel, warm_routes)
    for u in left:
        for oid in u.order_ids:
            reasons[oid] = "no_feasible_route"
    plans = plans_from_routes(routes_u)
    if st.dock == "cpsat":
        out = assign_docks_cpsat(ctx, plans, st.dock_time_s, st.seed, cancel)
    else:
        out = assign_docks_dispatch(ctx, plans, st.dock)
    reasons.update(out.unserved)
    assignments = [a for a in wh if a.frozen or a.order_ids[0] not in reasons]
    assignments += [load_assignment(r) for r in out.routes]
    # frozen routes are copied verbatim (history is never re-timed or rewritten)
    for fr in snap.frozen_routes:
        if fr.route is not None:
            out.routes.append(fr.route)
            if fr.route.dock_id and fr.route.load_start_min is not None:
                assignments.append(load_assignment(fr.route).model_copy(update={"frozen": True}))
    res = ScheduleResult(
        run_id="",
        algorithm=name,
        problem_type="integrated",
        status="FEASIBLE",
        assignments=sorted(assignments, key=lambda a: (a.start_min, a.task_id)),
        routes=sorted(out.routes, key=lambda r: r.vehicle_id),
        unserved_order_ids=sorted(reasons),
        unserved=unserved_list(snap, reasons),
        seed=st.seed,
        solver_metadata={
            "warehouse": st.warehouse,
            "routing": st.routing,
            "dock": st.dock,
            "warehouse_meta": wh_meta,
            "routing_meta": r_meta,
            "dock_meta": out.metadata,
        },
    )
    res.runtime_ms = int((time.perf_counter() - t0) * 1000)
    res.metrics = evaluate(snap, res)
    res.validation = validate_schedule(snap, res)
    return Composite(res, wh, pack_end, routes_u, {"elapsed_s": time.perf_counter() - t0})


def settings_from(config: SolveConfig, default_routing: str = "insertion") -> Settings:
    p = config.params
    budget = config.time_limit_s
    return Settings(
        warehouse=str(p.get("warehouse", "edd")),
        routing=str(p.get("routing", default_routing)),
        dock=str(p.get("dock", "cpsat")),
        wh_time_s=float(p.get("wh_time_s", max(1.0, budget * 0.3))),
        routing_time_s=float(p.get("routing_time_s", max(1.0, budget * 0.4))),
        dock_time_s=float(p.get("dock_time_s", max(1.0, budget * 0.2))),
        seed=config.seed,
    )


class SequentialIntegrated:
    """One-pass decomposition baseline (no feedback)."""

    name = "integrated_sequential"
    kind = "decomposition"
    supported_problem_types = {"integrated"}
    description = "순차 분해: 창고 → 준비시각 → VRPTW → 도크 → 재평가 (피드백 없음)"

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        st = settings_from(config)
        if "dock" not in config.params:
            st.dock = "edd"
        comp = compose(instance, instance, st, self.name, cancel)
        comp.result.solver_metadata["mode"] = "one-pass sequential decomposition"
        return comp.result
