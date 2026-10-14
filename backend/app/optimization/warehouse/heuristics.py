"""Warehouse dispatch rules adapted to the pick→pack multi-resource setting.

* FIFO — order release time (arrival into the DC), then order id.
* EDD  — order ship cutoff (due), then priority (urgent first), then release.
* SPT  — task processing time, then due.

Each rule only defines the task priority; placement is the shared serial SGS (earliest feasible
start on eligible workers / stations / equipment within shifts and downtime).
"""

from __future__ import annotations

import time

from app.optimization.common.contracts import (
    CancellationToken,
    ScenarioSnapshot,
    ScheduleResult,
    SolveConfig,
    Task,
)
from app.optimization.common.preprocess import prepare, unserved_list
from app.optimization.warehouse.sgs import TaskKey, decode

_TYPE_RANK = {"PICK": 0, "PACK": 1}


def fifo_key(snap: ScenarioSnapshot) -> TaskKey:
    om = snap.order_map()
    return lambda t: (om[t.order_id].release_min, t.order_id, _TYPE_RANK[t.type])


def edd_key(snap: ScenarioSnapshot) -> TaskKey:
    om = snap.order_map()
    return lambda t: (
        om[t.order_id].due_min,
        -om[t.order_id].priority,
        om[t.order_id].release_min,
        t.order_id,
        _TYPE_RANK[t.type],
    )


def spt_key(snap: ScenarioSnapshot) -> TaskKey:
    om = snap.order_map()
    return lambda t: (t.duration_min, om[t.order_id].due_min, t.order_id, _TYPE_RANK[t.type])


RULES = {"fifo": fifo_key, "edd": edd_key, "spt": spt_key}


class DispatchRuleScheduler:
    kind = "heuristic"
    supported_problem_types = {"warehouse"}

    def __init__(self, rule: str):
        self.rule = rule
        self.name = f"warehouse_{rule}"
        self.description = {
            "fifo": "FIFO 디스패치 (주문 도착순) + 직렬 SGS",
            "edd": "EDD 디스패치 (출고 마감 임박순, 긴급 우선) + 직렬 SGS",
            "spt": "SPT 디스패치 (작업시간 짧은 순) + 직렬 SGS",
        }[rule]

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        t0 = time.perf_counter()
        prep = prepare(instance, routing=False)
        res = decode(instance, prep, RULES[self.rule](instance))
        reasons = {**prep.unserved, **res.unserved}
        return ScheduleResult(
            run_id="",
            algorithm=self.name,
            problem_type="warehouse",
            status="FEASIBLE",  # heuristics never claim optimality
            assignments=res.assignments,
            routes=[],
            unserved_order_ids=sorted(reasons),
            unserved=unserved_list(instance, reasons),
            runtime_ms=int((time.perf_counter() - t0) * 1000),
            seed=config.seed,
            solver_metadata={"rule": self.rule, "scheme": "serial_sgs_gap_filling", "deterministic": True},
        )


def task_type_rank(t: Task) -> int:
    return _TYPE_RANK[t.type]
