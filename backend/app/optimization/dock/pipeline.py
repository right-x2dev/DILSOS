"""Problem type ``dock``: warehouse (dispatch rule) → shipment readiness → baseline grouping →
dock appointment (FIFO / EDD / CP-SAT) → timed delivery routes. All three dock algorithms share
the identical warehouse plan and grouping, so differences come only from dock decisions.
"""

from __future__ import annotations

import time

from app.optimization.common.contracts import (
    CancellationToken,
    ScenarioSnapshot,
    ScheduleResult,
    SolveConfig,
)
from app.optimization.common.preprocess import prepare, unserved_list
from app.optimization.common.routes import Ctx, load_assignment
from app.optimization.dock.cp_sat import assign_docks_cpsat
from app.optimization.dock.grouping import baseline_grouping
from app.optimization.dock.heuristics import assign_docks_dispatch
from app.optimization.warehouse.heuristics import RULES
from app.optimization.warehouse.sgs import decode


class DockScheduler:
    supported_problem_types = {"dock"}

    def __init__(self, method: str):
        self.method = method
        self.name = f"dock_{method}"
        self.kind = "exact" if method == "cpsat" else "heuristic"
        self.description = {
            "fifo": "도크 FIFO (출고 준비 완료순) + 최조 가용 도크",
            "edd": "도크 EDD (배송 여유시간 최소순) + 최조 가용 도크",
            "cpsat": "도크 CP-SAT (도크 NoOverlap + 하류 배송시각 정확 전파)",
        }[method]

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        t0 = time.perf_counter()
        snap = instance
        ctx = Ctx(snap)
        wh_rule = str(config.params.get("warehouse_rule", "edd"))
        prep = prepare(snap, routing=True)
        wh = decode(snap, prep, RULES[wh_rule](snap))
        reasons = {**prep.unserved, **wh.unserved}
        packed = [o for o in prep.servable if o not in wh.unserved]
        plans, grp_unserved = baseline_grouping(ctx, packed, wh.pack_end)
        reasons.update(grp_unserved)
        if self.method == "cpsat":
            out = assign_docks_cpsat(
                ctx, plans, config.time_limit_s, config.seed, cancel, config.params.get("num_workers")
            )
        else:
            out = assign_docks_dispatch(ctx, plans, self.method)
        reasons.update(out.unserved)
        # Orders that will not ship must not silently consume warehouse capacity: drop their
        # (non-frozen) pick/pack work. Executed (frozen) work is history and stays.
        assignments = [a for a in wh.assignments if a.frozen or a.order_ids[0] not in reasons]
        assignments += [load_assignment(r) for r in out.routes]
        # Never OPTIMAL: even an optimal dock sub-problem is conditional on the fixed upstream plan.
        status = "FEASIBLE"
        return ScheduleResult(
            run_id="",
            algorithm=self.name,
            problem_type="dock",
            status=status,  # type: ignore[arg-type]
            assignments=sorted(assignments, key=lambda a: (a.start_min, a.task_id)),
            routes=sorted(out.routes, key=lambda r: r.vehicle_id),
            unserved_order_ids=sorted(reasons),
            unserved=unserved_list(snap, reasons),
            runtime_ms=int((time.perf_counter() - t0) * 1000),
            seed=config.seed,
            solver_metadata={
                "warehouse_rule": wh_rule,
                "grouping": "baseline first-fit + nearest-neighbour (fixed)",
                "routes": len(out.routes),
                "optimality_note": "dock sub-problem only; upstream/grouping fixed",
                **out.metadata,
            },
        )
