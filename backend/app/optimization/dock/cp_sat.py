"""CP-SAT dock appointment model with exact downstream delivery timing for fixed stop sequences.

For each route r (optional: served_r):
  x_{r,d}                    route loads at compatible dock d (optional interval, NoOverlap per dock
                             together with blocked dock hours / downtime and frozen loads)
  s_r ≥ max(ready_r, shift_start_v, now);  e_r = s_r + load_r;  dep_r = e_r
  A_1 = dep_r + t(depot,1);  S_k = max(A_k, a_k);  A_{k+1} = S_k + svc_k + t(k,k+1)
  late_k ≥ S_k − b_k  (soft)  or  S_k ≤ b_k (hard);   S_last + svc + t(last,depot) ≤ shift_end_v
Objective: Σ priority·late_penalty·late_k (per order on the stop) + unserved penalties + Σ dep_r (tie-break).
"""

from __future__ import annotations

import os
import time

from ortools.sat.python import cp_model

from app.optimization.common.contracts import CancellationToken
from app.optimization.common.routes import Ctx, RoutePlan, compatible_docks, repair_plan, time_route
from app.optimization.dock.heuristics import DockOutcome, assign_docks_dispatch, earliest_load


class _Cb(cp_model.CpSolverSolutionCallback):
    def __init__(self, cancel: CancellationToken | None):
        super().__init__()
        self.cancel = cancel
        self.n = 0
        self.t0 = time.perf_counter()
        self.first: float | None = None

    def on_solution_callback(self) -> None:
        self.n += 1
        if self.first is None:
            self.first = time.perf_counter() - self.t0
        if self.cancel is not None and self.cancel.cancelled:
            self.stop_search()


def assign_docks_cpsat(
    ctx: Ctx,
    plans: list[RoutePlan],
    time_limit_s: float,
    seed: int,
    cancel: CancellationToken | None = None,
    num_workers: int | None = None,
) -> DockOutcome:
    snap = ctx.snap
    H = snap.horizon_min
    w = snap.weights
    hard = snap.params.time_window_mode == "hard"
    pre_dropped: dict[str, str] = {}
    # 1) remove stops that are infeasible even with the earliest possible loading (best case)
    clean: list[RoutePlan] = []
    for p in plans:
        if not p.stops:
            continue
        est = earliest_load(ctx, p)
        p2, route, dropped = repair_plan(
            ctx,
            RoutePlan(p.vehicle_id, list(p.stops), p.ready_min),
            lambda q, est=est: est + ctx.load_minutes(len(q.order_ids)),
        )
        pre_dropped.update(dropped)
        if route is not None:
            clean.append(p2)
    hint = assign_docks_dispatch(ctx, [RoutePlan(p.vehicle_id, list(p.stops), p.ready_min) for p in clean], "edd")
    hint_by_v = {r.vehicle_id: r for r in hint.routes}

    m = cp_model.CpModel()
    dock_ivs: dict[str, list] = {r.id: [] for r in snap.resources if r.kind == "dock"}
    served, start, pres = {}, {}, {}
    obj = []
    for p in clean:
        v = ctx.vm[p.vehicle_id]
        n = len(p.order_ids)
        L = ctx.load_minutes(n)
        lb = earliest_load(ctx, p)
        sv = m.new_bool_var(f"served_{p.vehicle_id}")
        served[p.vehicle_id] = sv
        s = m.new_int_var(lb, max(lb, H - L), f"s_{p.vehicle_id}")
        e = m.new_int_var(lb + L, max(lb, H - L) + L, f"e_{p.vehicle_id}")
        m.add(e == s + L)
        start[p.vehicle_id] = s
        xs = []
        for d in compatible_docks(ctx, p.vehicle_id):
            x = m.new_bool_var(f"x_{p.vehicle_id}_{d}")
            dock_ivs[d].append(m.new_optional_interval_var(s, L, e, x, f"iv_{p.vehicle_id}_{d}"))
            pres[(p.vehicle_id, d)] = x
            xs.append(x)
        m.add(sum(xs) == sv)
        # downstream propagation
        prev = ctx.depot
        t_prev = e
        for k, oids in enumerate(p.stops):
            c = ctx.cm[ctx.om[oids[0]].customer_id]
            loc = ctx.li[c.location_id]
            arr = m.new_int_var(0, 4 * H, f"A_{p.vehicle_id}_{k}")
            m.add(arr == t_prev + ctx.travel(prev, loc))
            st = m.new_int_var(0, 4 * H, f"S_{p.vehicle_id}_{k}")
            m.add_max_equality(st, [arr, m.new_constant(c.tw_start)])
            if hard:
                m.add(st <= c.tw_end).only_enforce_if(sv)
            else:
                late = m.new_int_var(0, 4 * H, f"late_{p.vehicle_id}_{k}")
                m.add(late >= st - c.tw_end).only_enforce_if(sv)
                pr = sum(ctx.om[o].priority for o in oids)
                obj.append(round(w.late_penalty_per_min * pr) * late)
            t_prev = st + c.service_min
            prev = loc
        ret = t_prev + (ctx.travel(prev, ctx.depot) if snap.params.return_to_depot else 0)
        m.add(ret <= min(v.shift_end, H)).only_enforce_if(sv)
        obj.append(round(w.unserved_penalty * sum(ctx.om[o].priority for o in p.order_ids)) * (1 - sv))
        obj.append(e)  # tie-break: earlier departures
        hr = hint_by_v.get(p.vehicle_id)
        m.add_hint(sv, 1 if hr else 0)
        if hr:
            m.add_hint(s, hr.load_start_min)  # type: ignore[arg-type]
            for d in compatible_docks(ctx, p.vehicle_id):
                m.add_hint(pres[(p.vehicle_id, d)], 1 if hr.dock_id == d else 0)
    for r in snap.resources:
        if r.kind != "dock":
            continue
        cur = 0
        for win in sorted(r.available, key=lambda i: i.start):
            if win.start > cur:
                dock_ivs[r.id].append(m.new_fixed_size_interval_var(cur, win.start - cur, "blk"))
            cur = max(cur, win.end)
        if cur < H:
            dock_ivs[r.id].append(m.new_fixed_size_interval_var(cur, H - cur, "blk"))
    for fr in snap.frozen_routes:
        if fr.dock_id in dock_ivs and fr.load_end > fr.load_start:
            dock_ivs[fr.dock_id].append(
                m.new_fixed_size_interval_var(fr.load_start, fr.load_end - fr.load_start, "frz")
            )
    for ivs in dock_ivs.values():
        if len(ivs) > 1:
            m.add_no_overlap(ivs)
    m.minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.random_seed = int(seed)
    workers = num_workers or min(8, os.cpu_count() or 1)
    solver.parameters.num_search_workers = workers
    cb = _Cb(cancel)
    st_code = solver.solve(m, cb)
    meta = {
        "dock_solver": "ortools.cp_sat",
        "dock_cp_status": solver.status_name(st_code),
        "dock_workers": workers,
        "dock_solutions": cb.n,
        "dock_time_to_first_s": round(cb.first, 3) if cb.first is not None else None,
        "dock_wall_s": round(solver.wall_time, 3),
    }
    out = DockOutcome(unserved=dict(pre_dropped), metadata=meta)
    if st_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        hint.unserved.update(pre_dropped)
        hint.metadata.update(meta, dock_fallback_used="dock_edd", dock_has_incumbent=False)
        return hint
    meta.update(
        dock_objective=solver.objective_value,
        dock_bound=solver.best_objective_bound,
        dock_gap=round(
            abs(solver.objective_value - solver.best_objective_bound) / max(1.0, abs(solver.objective_value)), 6
        ),
        dock_optimal=st_code == cp_model.OPTIMAL,
        dock_has_incumbent=True,
    )
    for p in clean:
        if not solver.value(served[p.vehicle_id]):
            for oid in p.order_ids:
                out.unserved[oid] = "no_feasible_dock_slot"
            continue
        dock = next(d for d in compatible_docks(ctx, p.vehicle_id) if solver.value(pres[(p.vehicle_id, d)]))
        s0 = int(solver.value(start[p.vehicle_id]))
        plan = RoutePlan(p.vehicle_id, list(p.stops), p.ready_min, dock, s0)
        out.routes.append(time_route(ctx, plan, s0 + ctx.load_minutes(len(plan.order_ids))))
    return out
