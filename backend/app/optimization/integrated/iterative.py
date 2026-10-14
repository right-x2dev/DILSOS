"""Iterative coordination between warehouse, dock and routing (spec §4.5 "advanced").

  0. feasible initial plan = sequential decomposition (incumbent);
  1. from the incumbent's routes derive each order's *required packing cutoff*:
         cutoff_o = (latest on-time departure of its route) − loading time − margin
     (latest on-time departure = min over stops of tw_end − cumulative travel/service, ignoring waits);
     late routes additionally pull their orders forward by the observed lateness;
  2. tighten the warehouse working copy's due dates to min(original, cutoff_o) so EDD/CP-SAT
     prioritise orders whose trucks are waiting;
  3. re-plan warehouse, re-route (warm-started from the incumbent), re-assign docks;
  4. accept only if the candidate validates as feasible AND improves the shared total cost;
     on rejection the margin is diversified (controlled), otherwise it is kept;
  5. stop on iteration limit, time budget, cancellation or 2 consecutive non-improving iterations.
The best feasible incumbent is returned. No global optimality is claimed (heuristic coordination).
"""

from __future__ import annotations

import time
from typing import Any

from app.optimization.common.contracts import CancellationToken, ScenarioSnapshot, ScheduleResult, SolveConfig
from app.optimization.common.routes import Ctx, RoutePlan, slack_departure
from app.optimization.integrated.decomposition import compose, settings_from


def departure_cutoffs(snap: ScenarioSnapshot, result: ScheduleResult, margin: int) -> dict[str, int]:
    ctx = Ctx(snap)
    cut: dict[str, int] = {}
    for r in result.routes:
        plan = RoutePlan(r.vehicle_id, [list(s.order_ids) for s in r.stops], r.ready_min)
        latest_dep = slack_departure(ctx, plan)
        late = max((s.late_min for s in r.stops), default=0)
        target = min(latest_dep, r.departure_min - late) - ctx.load_minutes(len(r.order_ids)) - margin
        for oid in r.order_ids:
            cut[oid] = target
    return cut


class IterativeIntegrated:
    name = "integrated_iterative"
    kind = "decomposition"
    supported_problem_types = {"integrated"}
    description = "반복 조정: 하류 출발 마감을 창고 우선순위로 피드백 → 재계획 → 개선 시에만 채택"

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        t0 = time.perf_counter()
        st = settings_from(config)
        max_iter = int(config.params.get("max_iterations", 5))
        budget = float(config.time_limit_s)
        margin = int(config.params.get("cutoff_margin_min", 10))
        snap = instance
        inc = compose(snap, snap, st, self.name, cancel)
        if not (inc.result.validation and inc.result.validation.is_feasible):
            inc.result.solver_metadata["coordination"] = "initial plan infeasible; returned for inspection"
            return inc.result
        m0 = inc.result.metrics
        assert m0 is not None  # compose() always evaluates
        history: list[dict[str, Any]] = [
            {
                "iter": 0,
                "total_cost": m0.cost.total_cost,
                "accepted": True,
                "late_min": m0.total_lateness_min,
                "margin": margin,
            }
        ]
        stall = 0
        it = 0
        for it in range(1, max_iter + 1):
            if cancel is not None and cancel.cancelled:
                break
            if time.perf_counter() - t0 + inc.meta["elapsed_s"] > budget:
                break
            cut = departure_cutoffs(snap, inc.result, margin)
            orders = [
                o.model_copy(update={"due_min": min(o.due_min, cut[o.id])}) if o.id in cut else o for o in snap.orders
            ]
            work = snap.model_copy(update={"orders": orders})
            cand = compose(snap, work, st, self.name, cancel, warm_routes=inc.routes_units)
            ok = bool(cand.result.validation and cand.result.validation.is_feasible)
            c_new = cand.result.metrics.cost.total_cost if cand.result.metrics else float("inf")
            c_old = inc.result.metrics.cost.total_cost  # type: ignore[union-attr]
            accepted = ok and c_new < c_old - 1e-6
            history.append(
                {
                    "iter": it,
                    "total_cost": c_new,
                    "accepted": accepted,
                    "feasible": ok,
                    "late_min": cand.result.metrics.total_lateness_min if cand.result.metrics else None,
                    "margin": margin,
                }
            )
            if accepted:
                inc, stall = cand, 0
            else:
                stall += 1
                margin = margin + 15 if stall == 1 else max(0, margin - 10)  # controlled diversification
                if stall >= 2:
                    break
        res = inc.result
        res.runtime_ms = int((time.perf_counter() - t0) * 1000)
        res.solver_metadata.update(
            mode="iterative coordination (feedback of departure cutoffs to warehouse priorities)",
            iterations=it,
            history=history,
            budget_s=budget,
            improvement_vs_initial=round(history[0]["total_cost"] - res.metrics.cost.total_cost, 2),  # type: ignore[union-attr]
            optimality="not proven (heuristic coordination)",
        )
        return res
