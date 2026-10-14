"""OR-Tools CP-SAT model for warehouse pick/pack scheduling (multi-resource RCPSP).

Variables
  s_t                   start of task t (integer minutes), e_t = s_t + p_t
  x_{t,q,k}             task t uses eligible resource k for requirement q (optional interval)
  served_o              order o is fulfilled (else explicitly unserved with penalty)
  late_o >= C_o - due_o lateness of order completion vs ship cutoff (only when served)
  ot_{t,k} >= e_t - regular_end_k  overtime minutes of task t on worker k (only when x)
Constraints
  sum_k x_{t,q,k} = served_o                    exactly one eligible resource per requirement
  NoOverlap(resource k) over optional intervals + blocked (off-shift / downtime) + frozen intervals
  s_succ >= e_pred                              pick precedes pack
  s_t >= max(release_t, current_time)           release dates / no rescheduling into the past
Objective (integer KRW)
  labor + overtime + late penalty + unserved penalty + 1·Σ completion (tie-break compaction)
The solver objective is *reported separately*; cross-algorithm comparison always uses the shared
evaluator (app.optimization.common.objectives).
"""

from __future__ import annotations

import os
import time

from ortools.sat.python import cp_model

from app.optimization.common.contracts import (
    CancellationToken,
    ScenarioSnapshot,
    ScheduleResult,
    SolveConfig,
    TaskAssignment,
)
from app.optimization.common.preprocess import prepare, unserved_list
from app.optimization.warehouse.heuristics import edd_key
from app.optimization.warehouse.sgs import decode


class _StopCb(cp_model.CpSolverSolutionCallback):
    def __init__(self, cancel: CancellationToken | None):
        super().__init__()
        self.cancel = cancel
        self.solutions = 0
        self.first_solution_s: float | None = None
        self.t0 = time.perf_counter()

    def on_solution_callback(self) -> None:
        self.solutions += 1
        if self.first_solution_s is None:
            self.first_solution_s = time.perf_counter() - self.t0
        if self.cancel is not None and self.cancel.cancelled:
            self.stop_search()


class WarehouseCpSat:
    name = "warehouse_cpsat"
    kind = "exact"
    supported_problem_types = {"warehouse"}
    description = "OR-Tools CP-SAT (선택적 구간·NoOverlap) — 시간 제한 내 최적/최선 해, EDD 해를 힌트로 사용"

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        t0 = time.perf_counter()
        snap = instance
        prep = prepare(snap, routing=False)
        hint = decode(snap, prep, edd_key(snap))
        reasons = dict(prep.unserved)
        H = snap.horizon_min
        tmap = snap.task_map()
        om = snap.order_map()
        rmap = snap.resource_map()
        w = snap.weights
        frozen = {f.task_id: f for f in snap.frozen_assignments}

        m = cp_model.CpModel()
        servable = list(prep.servable)
        served = {o: m.new_bool_var(f"served_{o}") for o in servable}
        tasks = [t for t in snap.tasks if t.order_id in served and t.id not in frozen]

        start, end = {}, {}
        res_intervals: dict[str, list] = {r.id: [] for r in snap.resources}
        presence: dict[tuple[str, str, str], cp_model.IntVar] = {}
        labor_terms, ot_terms = [], []

        for t in tasks:
            lb = max(t.release_min, snap.current_time_min)
            ub = H - t.duration_min
            if ub < lb:
                m.add(served[t.order_id] == 0)
                lb, ub = 0, max(0, H - t.duration_min)
            s = m.new_int_var(lb, ub, f"s_{t.id}")
            e = m.new_int_var(lb + t.duration_min, ub + t.duration_min, f"e_{t.id}")
            m.add(e == s + t.duration_min)
            start[t.id], end[t.id] = s, e
            for q in t.requirements:
                xs = []
                for k in q.eligible_ids:
                    x = m.new_bool_var(f"x_{t.id}_{k}")
                    iv = m.new_optional_interval_var(s, t.duration_min, e, x, f"iv_{t.id}_{k}")
                    res_intervals[k].append(iv)
                    presence[(t.id, q.kind, k)] = x
                    xs.append(x)
                    r = rmap[k]
                    if r.kind == "worker":
                        labor_terms.append(round(t.duration_min * r.hourly_cost / 60) * x)
                        if r.regular_end is not None and r.regular_end < ub + t.duration_min:
                            ot = m.new_int_var(0, t.duration_min, f"ot_{t.id}_{k}")
                            m.add(ot >= e - r.regular_end).only_enforce_if(x)
                            ot_terms.append(round(r.hourly_cost * w.overtime_premium / 60 * 100) * ot)
                m.add(sum(xs) == served[t.order_id])

        # blocked windows + frozen work on every resource
        for r in snap.resources:
            cursor = 0
            for win in sorted(r.available, key=lambda i: i.start):
                if win.start > cursor:
                    res_intervals[r.id].append(m.new_fixed_size_interval_var(cursor, win.start - cursor, "blk"))
                cursor = max(cursor, win.end)
            if cursor < H:
                res_intervals[r.id].append(m.new_fixed_size_interval_var(cursor, H - cursor, "blk"))
        for f in snap.frozen_assignments:
            for k in f.resources.values():
                if k in res_intervals and f.end_min > f.start_min:
                    res_intervals[k].append(m.new_fixed_size_interval_var(f.start_min, f.end_min - f.start_min, "frz"))
        for ivs in res_intervals.values():
            if len(ivs) > 1:
                m.add_no_overlap(ivs)

        for t in tasks:
            for p in t.predecessors:
                if p in end:
                    m.add(start[t.id] >= end[p])
                elif p in frozen:
                    m.add(start[t.id] >= frozen[p].end_min)

        # completion / lateness
        late_terms, unserved_terms, completion_terms = [], [], []
        for oid in servable:
            o = om[oid]
            ends = [end[t.id] for t in tasks if t.order_id == oid]
            fixed_end = max((f.end_min for f in snap.frozen_assignments if tmap[f.task_id].order_id == oid), default=0)
            if not ends:
                c_val = fixed_end
                late_terms.append(round(o.priority * w.late_penalty_per_min) * max(0, c_val - o.due_min) * served[oid])
                continue
            c = m.new_int_var(0, H, f"C_{oid}")
            m.add_max_equality(c, ends + ([m.new_constant(fixed_end)] if fixed_end else []))
            late = m.new_int_var(0, H, f"late_{oid}")
            m.add(late >= c - o.due_min).only_enforce_if(served[oid])
            late_terms.append(round(o.priority * w.late_penalty_per_min) * late)
            unserved_terms.append(round(o.priority * w.unserved_penalty) * (1 - served[oid]))
            completion_terms.append(c)

        # ot coefficient was scaled by 100 to keep precision; scale the rest equally
        m.minimize(
            100 * sum(labor_terms)
            + sum(ot_terms)
            + 100 * sum(late_terms)
            + 100 * sum(unserved_terms)
            + 100 * sum(completion_terms)
        )

        # warm start from EDD-SGS
        hinted = {a.task_id: a for a in hint.assignments if not a.frozen}
        for t in tasks:
            a = hinted.get(t.id)
            if a is None:
                continue
            m.add_hint(start[t.id], a.start_min)
            for q in t.requirements:
                for k in q.eligible_ids:
                    m.add_hint(presence[(t.id, q.kind, k)], 1 if a.resources.get(q.kind) == k else 0)
        for oid, v in served.items():
            m.add_hint(v, 0 if oid in hint.unserved else 1)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(config.time_limit_s)
        solver.parameters.random_seed = int(config.seed)
        workers = int(config.params.get("num_workers", min(8, os.cpu_count() or 1)))
        solver.parameters.num_search_workers = workers
        cb = _StopCb(cancel)
        st = solver.solve(m, cb)
        wall = time.perf_counter() - t0

        meta = {
            "solver": "ortools.cp_sat",
            "cp_status": solver.status_name(st),
            "num_workers": workers,
            "time_limit_s": config.time_limit_s,
            "wall_time_s": round(solver.wall_time, 3),
            "solutions_found": cb.solutions,
            "time_to_first_feasible_s": round(cb.first_solution_s, 3) if cb.first_solution_s is not None else None,
            "objective_scale": "KRW x100 (incl. 1 KRW/min completion tie-break)",
            "variables": len(m.proto.variables),
            "constraints": len(m.proto.constraints),
            "deterministic": workers == 1,
            "cancelled": bool(cancel and cancel.cancelled),
        }
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            obj, bound = solver.objective_value, solver.best_objective_bound
            meta.update(
                solver_objective=obj,
                best_bound=bound,
                gap=round(abs(obj - bound) / max(1.0, abs(obj)), 6),
                has_incumbent=True,
            )
            assignments = list(a for a in hint.assignments if a.frozen)
            for t in tasks:
                if not solver.value(served[t.order_id]):
                    continue
                chosen: dict[str, str] = {}
                for q in t.requirements:
                    for k in q.eligible_ids:
                        if solver.value(presence[(t.id, q.kind, k)]):
                            chosen[q.kind] = k
                s0 = int(solver.value(start[t.id]))
                assignments.append(
                    TaskAssignment(
                        task_id=t.id,
                        task_type=t.type,
                        order_ids=[t.order_id],
                        resource_id=chosen[t.requirements[0].kind],
                        resources=chosen,
                        start_min=s0,
                        end_min=s0 + t.duration_min,
                    )
                )
            for oid, v in served.items():
                if not solver.value(v):
                    reasons[oid] = "not_scheduled_by_optimizer"
            if st == cp_model.OPTIMAL:
                status = "OPTIMAL"
            elif wall >= config.time_limit_s * 0.95 or meta["cancelled"]:
                status = "TIME_LIMIT"
            else:
                status = "FEASIBLE"
        elif st == cp_model.INFEASIBLE:
            assignments, status = [], "INFEASIBLE"
            meta["has_incumbent"] = False
        else:  # UNKNOWN: no incumbent within budget → documented fallback to the EDD warm start
            assignments = hint.assignments
            reasons.update(hint.unserved)
            status = "TIME_LIMIT"
            meta.update(has_incumbent=False, fallback_used="warehouse_edd_warm_start")

        assignments.sort(key=lambda a: (a.start_min, a.task_id))
        return ScheduleResult(
            run_id="",
            algorithm=self.name,
            problem_type="warehouse",
            status=status,  # type: ignore[arg-type]
            assignments=assignments,
            routes=[],
            unserved_order_ids=sorted(reasons),
            unserved=unserved_list(snap, reasons),
            runtime_ms=int(wall * 1000),
            seed=config.seed,
            solver_metadata=meta,
        )
