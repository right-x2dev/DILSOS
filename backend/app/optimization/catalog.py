"""Single place where algorithms are registered (imported lazily by the registry)."""

from __future__ import annotations

from collections.abc import Callable

from app.optimization.common.contracts import SchedulingAlgorithm
from app.optimization.common.registry import register
from app.optimization.dock.pipeline import DockScheduler
from app.optimization.integrated.decomposition import SequentialIntegrated
from app.optimization.integrated.iterative import IterativeIntegrated
from app.optimization.routing.pipeline import RoutingScheduler
from app.optimization.warehouse.cp_sat import WarehouseCpSat
from app.optimization.warehouse.heuristics import DispatchRuleScheduler
from app.optimization.warehouse.metaheuristics import WarehouseMetaheuristic


def _rule_factory(rule: str) -> Callable[[], SchedulingAlgorithm]:
    return lambda: DispatchRuleScheduler(rule)


for _rule, _desc in (
    ("fifo", "FIFO dispatch (order arrival) + serial SGS"),
    ("edd", "EDD dispatch (ship cutoff, urgent first) + serial SGS"),
    ("spt", "SPT dispatch (shortest processing time) + serial SGS"),
):
    register(f"warehouse_{_rule}", ("warehouse",), "heuristic", _desc, _rule_factory(_rule))


def _dock_factory(method: str) -> Callable[[], SchedulingAlgorithm]:
    return lambda: DockScheduler(method)


for _m, _desc, _kind in (
    ("fifo", "Dock FIFO by shipment readiness; EDD warehouse + baseline grouping", "heuristic"),
    ("edd", "Dock EDD by delivery slack; EDD warehouse + baseline grouping", "heuristic"),
    ("cpsat", "Dock CP-SAT with exact downstream delivery timing (fixed upstream)", "exact"),
):
    register(
        f"dock_{_m}",
        ("dock",),
        _kind,
        _desc,
        _dock_factory(_m),
        requires=("ortools",) if _m == "cpsat" else (),
        phase="P2",
    )


def _routing_factory(method: str) -> Callable[[], SchedulingAlgorithm]:
    return lambda: RoutingScheduler(method)


for _m, _desc, _kind in (
    ("nn", "Time-oriented nearest neighbour VRPTW (+ cheapest insertion of leftovers)", "heuristic"),
    ("insertion", "Cheapest insertion VRPTW (fixed + distance + lateness cost)", "heuristic"),
    ("ortools", "OR-Tools Routing VRPTW: capacity/time dimensions, soft/hard windows, GLS", "metaheuristic"),
):
    register(
        f"routing_{_m}",
        ("routing",),
        _kind,
        _desc,
        _routing_factory(_m),
        requires=("ortools",) if _m == "ortools" else (),
        phase="P3",
    )

register(
    "routing_alns",
    ("routing",),
    "metaheuristic",
    "ALNS: random/worst/related/route removal, greedy/regret-2 repair, adaptive weights, SA acceptance",
    _routing_factory("alns"),
    stochastic=True,
    phase="P5",
)


def _meta_factory(method: str) -> Callable[[], SchedulingAlgorithm]:
    return lambda: WarehouseMetaheuristic(method)


for _m, _desc in (
    ("sa", "Simulated annealing over order permutations (SGS decoder, feasible by construction)"),
    ("tabu", "Tabu search over order permutations (swap neighbourhood, aspiration)"),
    ("ga", "Genetic algorithm (OX crossover, swap mutation, elitism) over order permutations"),
):
    register(f"warehouse_{_m}", ("warehouse",), "metaheuristic", _desc, _meta_factory(_m), stochastic=True, phase="P5")

register(
    "integrated_sequential",
    ("integrated",),
    "decomposition",
    "One-pass decomposition: warehouse → readiness → VRPTW → docks → re-evaluate",
    SequentialIntegrated,
    phase="P4",
)
register(
    "integrated_iterative",
    ("integrated",),
    "decomposition",
    "Iterative coordination: downstream departure cutoffs fed back to warehouse priorities",
    IterativeIntegrated,
    requires=("ortools",),
    phase="P4",
)

register(
    "warehouse_cpsat",
    ("warehouse",),
    "exact",
    "OR-Tools CP-SAT with optional intervals, shifts/downtime, EDD warm start",
    WarehouseCpSat,
    requires=("ortools",),
)
