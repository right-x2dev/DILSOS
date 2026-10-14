"""Single place where algorithms are registered (imported lazily by the registry)."""

from __future__ import annotations

from collections.abc import Callable

from app.optimization.common.contracts import SchedulingAlgorithm
from app.optimization.common.registry import register
from app.optimization.warehouse.cp_sat import WarehouseCpSat
from app.optimization.warehouse.heuristics import DispatchRuleScheduler


def _rule_factory(rule: str) -> Callable[[], SchedulingAlgorithm]:
    return lambda: DispatchRuleScheduler(rule)


for _rule, _desc in (
    ("fifo", "FIFO dispatch (order arrival) + serial SGS"),
    ("edd", "EDD dispatch (ship cutoff, urgent first) + serial SGS"),
    ("spt", "SPT dispatch (shortest processing time) + serial SGS"),
):
    register(f"warehouse_{_rule}", ("warehouse",), "heuristic", _desc, _rule_factory(_rule))

register(
    "warehouse_cpsat",
    ("warehouse",),
    "exact",
    "OR-Tools CP-SAT with optional intervals, shifts/downtime, EDD warm start",
    WarehouseCpSat,
    requires=("ortools",),
)
